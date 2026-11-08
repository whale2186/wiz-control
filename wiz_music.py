# File: wiz_music.py
"""WiZ Light Music Synchronizer.

Captures live audio from system microphones or loopback monitors, analyzes
frequency bands (bass, mids, treble) and beat transients in real time, and
maps music dynamics into low-latency UDP lighting commands for WiZ bulbs.
"""

from dataclasses import dataclass
import colorsys
import json
import logging
import math
import os
import random
import shutil
import socket
import subprocess
import sys
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

try:
    import numpy as np
except ImportError:
    np = None

try:
    import sounddevice as sd
except ImportError:
    sd = None

# Network Constants
WIZ_BROADCAST_PORT = 38899
DEFAULT_SAMPLE_RATE = 44100
DEFAULT_BLOCK_SIZE = 2048
DEFAULT_MIN_SEND_INTERVAL = 0.08  # Max ~12.5 updates/sec to protect bulb firmware
BEAT_COOLDOWN_SECONDS = 0.16      # Debounce to prevent multiple triggers per kick

# Frequency Band Definitions (Hz)
BASS_RANGE = (20, 250)
MID_RANGE = (250, 2500)
HIGH_RANGE = (2500, 10000)

SYNC_MODES = [
    "spectrum",
    "beat_pulse",
    "hue_flow",
    "chill_ambient",
    "disco",
]


@dataclass
class AudioFeatures:
    """Extracted audio features from a single frame."""

    volume: float = 0.0       # Normalized RMS amplitude (0.0 to 1.0)
    bass: float = 0.0         # Normalized low-frequency energy (0.0 to 1.0)
    mid: float = 0.0          # Normalized mid-frequency energy (0.0 to 1.0)
    high: float = 0.0         # Normalized high-frequency energy (0.0 to 1.0)
    is_beat: bool = False     # Beat transient detected in this frame
    peak: float = 0.0         # Peak sample amplitude (0.0 to 1.0)


@dataclass
class LightState:
    """Color and brightness state to dispatch to WiZ bulbs."""

    r: int = 255
    g: int = 255
    b: int = 255
    dimming: int = 100
    state: bool = True


def get_audio_devices() -> List[Dict[str, Any]]:
    """Enumerate audio input devices available on the system."""
    if sd is None:
        logging.warning("sounddevice is not installed; audio devices unavailable.")
        return []

    devices = []
    try:
        device_list = sd.query_devices()
        default_in = sd.default.device[0] if sd.default.device else None
        for idx, dev in enumerate(device_list):
            if dev.get("max_input_channels", 0) > 0:
                is_default = (idx == default_in)
                name = dev.get("name", f"Audio Device {idx}")
                devices.append({
                    "index": idx,
                    "name": name,
                    "channels": dev.get("max_input_channels", 1),
                    "default_samplerate": dev.get("default_samplerate", DEFAULT_SAMPLE_RATE),
                    "is_default": is_default,
                })
    except Exception as exc:
        logging.error("Failed to query audio devices: %s", exc)

    return devices


def configure_system_audio_monitor() -> Optional[int]:
    """Attempt to configure desktop/system audio monitor for live music capture."""
    # 1. On Linux with PulseAudio/PipeWire: query default sink and set monitor source
    try:
        pactl = shutil.which("pactl")
        if pactl:
            result = subprocess.run([pactl, "get-default-sink"], capture_output=True, text=True, check=True)
            default_sink = result.stdout.strip()
            if default_sink:
                monitor_source = f"{default_sink}.monitor"
                os.environ["PULSE_SOURCE"] = monitor_source
                if sd:
                    for idx, dev in enumerate(sd.query_devices()):
                        if dev.get("name") == "pulse" and dev.get("max_input_channels", 0) > 0:
                            logging.info("Auto-configured PulseAudio monitor: %s on device index %d", monitor_source, idx)
                            return idx
    except Exception as exc:
        logging.debug("Could not auto-configure PulseAudio monitor: %s", exc)

    # 2. Check for active media app streams directly exposed in JACK/PipeWire
    if sd:
        try:
            for idx, dev in enumerate(sd.query_devices()):
                name = dev.get("name", "").lower()
                if any(app in name for app in ("chrome", "spotify", "firefox", "vlc")) and dev.get("max_input_channels", 0) > 0:
                    logging.info("Selected application audio stream: %s (device %d)", dev.get("name"), idx)
                    return idx
        except Exception:
            pass

    return None


class AudioAnalyzer:
    """Real-time frequency and beat analyzer using FFT with dynamic AGC."""

    def __init__(
        self,
        sample_rate: int = DEFAULT_SAMPLE_RATE,
        block_size: int = DEFAULT_BLOCK_SIZE,
        sensitivity: float = 1.0,
    ):
        self.sample_rate = sample_rate
        self.block_size = block_size
        self.sensitivity = max(0.1, float(sensitivity))

        # Dynamic Automatic Gain Control (AGC) tracking
        self.avg_bass = 0.05
        self.avg_mid = 0.05
        self.avg_high = 0.05
        self.avg_vol = 0.05

        # Beat detection state
        self.last_beat_time = 0.0
        self.prev_bass_energy = 0.0

        # Precompute window & frequency bins if numpy is present
        if np is not None:
            self.window = np.hanning(self.block_size)
            freqs = np.fft.rfftfreq(self.block_size, 1.0 / self.sample_rate)
            self.bass_mask = (freqs >= BASS_RANGE[0]) & (freqs <= BASS_RANGE[1])
            self.mid_mask = (freqs > MID_RANGE[0]) & (freqs <= MID_RANGE[1])
            self.high_mask = (freqs > HIGH_RANGE[0]) & (freqs <= HIGH_RANGE[1])
        else:
            self.window = None
            self.bass_mask = None
            self.mid_mask = None
            self.high_mask = None

    def set_sensitivity(self, sensitivity: float) -> None:
        """Update sensitivity multiplier."""
        self.sensitivity = max(0.1, float(sensitivity))

    def analyze(self, audio_data: Any, now: Optional[float] = None) -> AudioFeatures:
        """Analyze a block of PCM audio data and extract AudioFeatures."""
        current_time = time.time() if now is None else float(now)

        if np is not None and isinstance(audio_data, np.ndarray):
            # Flatten to 1D mono
            if audio_data.ndim > 1:
                mono = np.mean(audio_data, axis=1)
            else:
                mono = audio_data

            length = len(mono)
            if length == 0:
                return AudioFeatures()

            # Align block size
            if length < self.block_size:
                mono = np.pad(mono, (0, self.block_size - length), mode="constant")
            elif length > self.block_size:
                mono = mono[: self.block_size]

            peak = float(np.max(np.abs(mono)))
            rms = float(np.sqrt(np.mean(mono ** 2)))

            # Windowed FFT
            windowed = mono * self.window
            fft_mag = np.abs(np.fft.rfft(windowed))

            # Band energies
            raw_bass = float(np.sum(fft_mag[self.bass_mask])) if self.bass_mask is not None else 0.0
            raw_mid = float(np.sum(fft_mag[self.mid_mask])) if self.mid_mask is not None else 0.0
            raw_high = float(np.sum(fft_mag[self.high_mask])) if self.high_mask is not None else 0.0
        else:
            # Fallback for plain Python lists/floats (e.g. mock unit tests)
            items = list(audio_data) if audio_data is not None else []
            if not items:
                return AudioFeatures()
            peak = max(abs(x) for x in items)
            rms = math.sqrt(sum(x * x for x in items) / len(items))
            raw_bass = rms * 0.5
            raw_mid = rms * 0.3
            raw_high = rms * 0.2

        total_fft = raw_bass + raw_mid + raw_high + 1e-5
        rel_bass = raw_bass / total_fft
        rel_mid = raw_mid / total_fft
        rel_high = raw_high / total_fft

        # Beat detection: check for sudden rise in bass energy compared to running average
        is_beat = False
        beat_threshold = max(1.15, 1.45 - 0.15 * min(self.sensitivity, 2.0))
        if raw_bass > self.avg_bass * beat_threshold and raw_bass > 0.02:
            if (current_time - self.last_beat_time) >= BEAT_COOLDOWN_SECONDS:
                is_beat = True
                self.last_beat_time = current_time

        # Update EMA running averages for AGC (decay factor ~0.95)
        alpha = 0.05
        self.avg_bass = (1.0 - alpha) * self.avg_bass + alpha * max(0.5, raw_bass)
        self.avg_mid = (1.0 - alpha) * self.avg_mid + alpha * max(0.5, raw_mid)
        self.avg_high = (1.0 - alpha) * self.avg_high + alpha * max(0.5, raw_high)
        self.avg_vol = (1.0 - alpha) * self.avg_vol + alpha * max(0.01, rms)

        # Normalize bands using AGC averages, relative energy, and user sensitivity
        norm_vol = min(1.0, max(0.0, (rms / (self.avg_vol * 1.8 + 1e-4)) * (self.sensitivity * 0.85)))
        norm_bass = min(1.0, max(0.0, (raw_bass / (self.avg_bass * 1.8 + 1e-4)) * rel_bass * (self.sensitivity * 1.3)))
        norm_mid = min(1.0, max(0.0, (raw_mid / (self.avg_mid * 1.8 + 1e-4)) * rel_mid * (self.sensitivity * 1.3)))
        norm_high = min(1.0, max(0.0, (raw_high / (self.avg_high * 1.8 + 1e-4)) * rel_high * (self.sensitivity * 1.3)))

        self.prev_bass_energy = raw_bass

        return AudioFeatures(
            volume=norm_vol,
            bass=norm_bass,
            mid=norm_mid,
            high=norm_high,
            is_beat=is_beat,
            peak=min(1.0, peak * self.sensitivity),
        )


class LightMapper:
    """Translates audio features into RGB colors and dimming levels for WiZ lights."""

    VIBRANT_PALETTE: List[Tuple[int, int, int]] = [
        (255, 0, 110),   # Neon Magenta
        (0, 240, 255),   # Electric Cyan
        (255, 190, 0),   # Vivid Amber
        (130, 0, 255),   # Royal Violet
        (0, 255, 120),   # Spring Lime
        (255, 45, 0),    # Blaze Orange
        (0, 140, 255),   # Azure Blue
    ]

    PASTEL_PALETTE: List[Tuple[int, int, int]] = [
        (255, 140, 180),  # Soft Rose
        (100, 210, 240),  # Sky Teal
        (180, 150, 245),  # Lilac
        (255, 200, 140),  # Warm Peach
        (120, 235, 195),  # Mint
    ]

    def __init__(
        self,
        mode: str = "spectrum",
        min_brightness: int = 10,
        max_brightness: int = 100,
        sensitivity: float = 1.0,
    ):
        self.mode = mode if mode in SYNC_MODES else "spectrum"
        self.min_brightness = max(10, min(100, int(min_brightness)))
        self.max_brightness = max(self.min_brightness, min(100, int(max_brightness)))
        self.sensitivity = max(0.1, float(sensitivity))

        # Dynamic state trackers
        self._current_dimming = float(self.min_brightness)
        self._hue = 0.0
        self._palette_idx = 0
        self._disco_color = (255, 0, 100)
        self._ambient_idx = 0.0
        self._curr_r = 100.0
        self._curr_g = 100.0
        self._curr_b = 255.0

    def set_mode(self, mode: str) -> None:
        """Change the synchronization mode."""
        if mode in SYNC_MODES:
            self.mode = mode

    def set_brightness_range(self, min_b: int, max_b: int) -> None:
        """Configure dimming boundary limits."""
        self.min_brightness = max(10, min(100, int(min_b)))
        self.max_brightness = max(self.min_brightness, min(100, int(max_b)))

    def set_sensitivity(self, sensitivity: float) -> None:
        """Update sensitivity."""
        self.sensitivity = max(0.1, float(sensitivity))

    def _clamp_dimming(self, value: float) -> int:
        return max(self.min_brightness, min(self.max_brightness, int(round(value))))

    def _clamp_rgb(self, r: float, g: float, b: float) -> Tuple[int, int, int]:
        return (
            max(0, min(255, int(round(r)))),
            max(0, min(255, int(round(g)))),
            max(0, min(255, int(round(b)))),
        )

    def map_features(self, features: AudioFeatures) -> LightState:
        """Map audio features to WiZ LightState based on selected mode."""
        if self.mode == "beat_pulse":
            return self._map_beat_pulse(features)
        elif self.mode == "hue_flow":
            return self._map_hue_flow(features)
        elif self.mode == "chill_ambient":
            return self._map_chill_ambient(features)
        elif self.mode == "disco":
            return self._map_disco(features)
        else:
            return self._map_spectrum(features)

    def _map_spectrum(self, features: AudioFeatures) -> LightState:
        """Spectrum Mode: Bass -> Red, Mids -> Green, Treble -> Blue."""
        # Non-linear curve to punch up saturated peaks
        r = (features.bass ** 1.3) * 255.0
        g = (features.mid ** 1.3) * 255.0
        b = (features.high ** 1.3) * 255.0

        # Enhance saturation so it does not degrade into greyish white
        max_c = max(r, g, b, 1.0)
        boost = 255.0 / max_c if max_c > 60 else 1.0
        r = min(255.0, r * boost * 0.9)
        g = min(255.0, g * boost * 0.9)
        b = min(255.0, b * boost * 0.9)

        # Smooth color transitions slightly
        smooth_decay = 0.55
        self._curr_r = self._curr_r * smooth_decay + r * (1.0 - smooth_decay)
        self._curr_g = self._curr_g * smooth_decay + g * (1.0 - smooth_decay)
        self._curr_b = self._curr_b * smooth_decay + b * (1.0 - smooth_decay)

        # Dimming calculated from combined energy and bass
        target_dimming = self.min_brightness + (self.max_brightness - self.min_brightness) * (
            0.5 * features.volume + 0.5 * features.bass
        )
        if features.is_beat:
            target_dimming = self.max_brightness

        self._current_dimming = max(
            float(self.min_brightness),
            self._current_dimming * 0.7 + target_dimming * 0.3,
        )

        clamped_r, clamped_g, clamped_b = self._clamp_rgb(self._curr_r, self._curr_g, self._curr_b)
        return LightState(
            r=clamped_r,
            g=clamped_g,
            b=clamped_b,
            dimming=self._clamp_dimming(self._current_dimming),
            state=True,
        )

    def _map_beat_pulse(self, features: AudioFeatures) -> LightState:
        """Beat Pulse: Flashes bright color on beat, decays smoothly between kicks."""
        if features.is_beat:
            self._palette_idx = (self._palette_idx + 1) % len(self.VIBRANT_PALETTE)
            self._current_dimming = float(self.max_brightness)
        else:
            # Exponential decay down to min_brightness
            decay_rate = 0.82
            self._current_dimming = max(
                float(self.min_brightness),
                self._current_dimming * decay_rate,
            )

        cur_color = self.VIBRANT_PALETTE[self._palette_idx]
        return LightState(
            r=cur_color[0],
            g=cur_color[1],
            b=cur_color[2],
            dimming=self._clamp_dimming(self._current_dimming),
            state=True,
        )

    def _map_hue_flow(self, features: AudioFeatures) -> LightState:
        """Hue Flow: Continuous rainbow color wheel rotation driven by music tempo."""
        # Speed advances with energy
        hue_step = 0.008 + (features.volume * 0.035) + (0.05 if features.is_beat else 0.0)
        self._hue = (self._hue + hue_step) % 1.0

        rgb_floats = colorsys.hsv_to_rgb(self._hue, 0.95, 1.0)
        r, g, b = (rgb_floats[0] * 255.0, rgb_floats[1] * 255.0, rgb_floats[2] * 255.0)

        target_dim = self.min_brightness + (self.max_brightness - self.min_brightness) * (
            0.6 * features.volume + 0.4 * features.bass
        )
        if features.is_beat:
            target_dim = self.max_brightness

        self._current_dimming = max(
            float(self.min_brightness),
            self._current_dimming * 0.75 + target_dim * 0.25,
        )

        clamped_r, clamped_g, clamped_b = self._clamp_rgb(r, g, b)
        return LightState(
            r=clamped_r,
            g=clamped_g,
            b=clamped_b,
            dimming=self._clamp_dimming(self._current_dimming),
            state=True,
        )

    def _map_chill_ambient(self, features: AudioFeatures) -> LightState:
        """Chill Ambient: Gentle relaxing pastel shifts with breathing brightness."""
        # Slow drift through pastel palette
        self._ambient_idx = (self._ambient_idx + 0.015 + 0.02 * features.mid) % len(self.PASTEL_PALETTE)
        idx_low = int(self._ambient_idx)
        idx_high = (idx_low + 1) % len(self.PASTEL_PALETTE)
        frac = self._ambient_idx - idx_low

        c1 = self.PASTEL_PALETTE[idx_low]
        c2 = self.PASTEL_PALETTE[idx_high]
        target_r = c1[0] * (1.0 - frac) + c2[0] * frac
        target_g = c1[1] * (1.0 - frac) + c2[1] * frac
        target_b = c1[2] * (1.0 - frac) + c2[2] * frac

        # Heavy smoothing to eliminate aggressive flicker
        self._curr_r = self._curr_r * 0.88 + target_r * 0.12
        self._curr_g = self._curr_g * 0.88 + target_g * 0.12
        self._curr_b = self._curr_b * 0.88 + target_b * 0.12

        target_dim = self.min_brightness + (self.max_brightness - self.min_brightness) * (
            0.7 * features.volume + 0.3 * features.mid
        )
        self._current_dimming = self._current_dimming * 0.85 + target_dim * 0.15

        clamped_r, clamped_g, clamped_b = self._clamp_rgb(self._curr_r, self._curr_g, self._curr_b)
        return LightState(
            r=clamped_r,
            g=clamped_g,
            b=clamped_b,
            dimming=self._clamp_dimming(self._current_dimming),
            state=True,
        )

    def _map_disco(self, features: AudioFeatures) -> LightState:
        """Disco Mode: Strobe flash and rapid color jumps on beat drops."""
        if features.is_beat:
            self._disco_color = random.choice(self.VIBRANT_PALETTE)
            self._current_dimming = float(self.max_brightness)
        else:
            self._current_dimming = max(
                float(self.min_brightness),
                self._current_dimming * 0.65,
            )

        return LightState(
            r=self._disco_color[0],
            g=self._disco_color[1],
            b=self._disco_color[2],
            dimming=self._clamp_dimming(self._current_dimming),
            state=True,
        )


class WizMusicSender:
    """Non-blocking UDP transmitter with rate-limiting and deadband checks."""

    def __init__(
        self,
        port: int = WIZ_BROADCAST_PORT,
        min_interval: float = DEFAULT_MIN_SEND_INTERVAL,
    ):
        self.port = port
        self.min_interval = min_interval
        self._socket: Optional[socket.socket] = None
        self._lock = threading.Lock()
        self._last_sent_times: Dict[str, float] = {}
        self._last_sent_states: Dict[str, LightState] = {}
        self._init_socket()

    def _init_socket(self) -> None:
        try:
            self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        except Exception as exc:
            logging.error("Failed to initialize UDP socket for WiZ sender: %s", exc)
            self._socket = None

    def close(self) -> None:
        """Close the socket connection."""
        with self._lock:
            if self._socket:
                try:
                    self._socket.close()
                except Exception:
                    pass
                self._socket = None

    def _is_significant_change(self, old: Optional[LightState], new: LightState) -> bool:
        if old is None:
            return True
        if old.state != new.state:
            return True
        if abs(old.dimming - new.dimming) >= 3:
            return True
        if abs(old.r - new.r) >= 6 or abs(old.g - new.g) >= 6 or abs(old.b - new.b) >= 6:
            return True
        return False

    def send(
        self,
        target_ips: List[str],
        state: LightState,
        force: bool = False,
    ) -> int:
        """Send a light state payload to target IPs without blocking."""
        if not target_ips:
            return 0

        with self._lock:
            if not self._socket:
                self._init_socket()
                if not self._socket:
                    return 0

            now = time.time()
            payload = json.dumps({
                "method": "setPilot",
                "params": {
                    "state": state.state,
                    "dimming": state.dimming,
                    "r": state.r,
                    "g": state.g,
                    "b": state.b,
                },
            }).encode("utf-8")

            sent_count = 0
            for ip in target_ips:
                last_time = self._last_sent_times.get(ip, 0.0)
                last_state = self._last_sent_states.get(ip)
                elapsed = now - last_time

                # Throttling logic: protect bulb firmware with safe minimum intervals
                min_wait = 0.065 if force else self.min_interval
                if elapsed < min_wait and not force:
                    continue

                if not force and not self._is_significant_change(last_state, state):
                    continue

                try:
                    self._socket.sendto(payload, (ip, self.port))
                    self._last_sent_times[ip] = now
                    self._last_sent_states[ip] = LightState(
                        r=state.r,
                        g=state.g,
                        b=state.b,
                        dimming=state.dimming,
                        state=state.state,
                    )
                    sent_count += 1
                except Exception as exc:
                    logging.debug("Error sending UDP pilot to %s: %s", ip, exc)

            return sent_count

    def turn_off(self, target_ips: List[str]) -> None:
        """Turn off target bulbs."""
        if not target_ips:
            return
        payload = json.dumps({"method": "setPilot", "params": {"state": False}}).encode("utf-8")
        with self._lock:
            if not self._socket:
                return
            for ip in target_ips:
                try:
                    self._socket.sendto(payload, (ip, self.port))
                except Exception:
                    pass


class WizMusicSynchronizer:
    """Orchestrates audio capture, analysis, light mapping, and network transmission."""

    def __init__(
        self,
        target_ips: List[str],
        device_index: Optional[int] = None,
        mode: str = "spectrum",
        sensitivity: float = 1.0,
        min_brightness: int = 10,
        max_brightness: int = 100,
        sample_rate: int = DEFAULT_SAMPLE_RATE,
        block_size: int = DEFAULT_BLOCK_SIZE,
        on_frame_callback: Optional[Callable[[AudioFeatures, LightState], None]] = None,
    ):
        self.target_ips = list(target_ips)
        self.device_index = device_index
        self.sample_rate = sample_rate
        self.block_size = block_size
        self.on_frame_callback = on_frame_callback

        self.analyzer = AudioAnalyzer(
            sample_rate=sample_rate,
            block_size=block_size,
            sensitivity=sensitivity,
        )
        self.mapper = LightMapper(
            mode=mode,
            min_brightness=min_brightness,
            max_brightness=max_brightness,
            sensitivity=sensitivity,
        )
        self.sender = WizMusicSender()

        self._running = False
        self._stream: Optional[Any] = None
        self._lock = threading.Lock()

    def is_running(self) -> bool:
        """Return True if music synchronization is actively running."""
        with self._lock:
            return self._running

    def set_target_ips(self, ips: List[str]) -> None:
        """Update target light IP addresses."""
        with self._lock:
            self.target_ips = list(ips)

    def set_mode(self, mode: str) -> None:
        """Switch visualizer mode."""
        self.mapper.set_mode(mode)

    def set_sensitivity(self, sensitivity: float) -> None:
        """Update sensitivity across analyzer and mapper."""
        self.analyzer.set_sensitivity(sensitivity)
        self.mapper.set_sensitivity(sensitivity)

    def set_brightness_range(self, min_b: int, max_b: int) -> None:
        """Update dimming boundaries."""
        self.mapper.set_brightness_range(min_b, max_b)

    def _audio_callback(self, indata: Any, frames: int, time_info: Any, status: Any) -> None:
        """Callback executed in the audio capture thread."""
        if not self._running:
            return

        try:
            features = self.analyzer.analyze(indata)
            light_state = self.mapper.map_features(features)

            with self._lock:
                ips = list(self.target_ips)

            self.sender.send(ips, light_state, force=features.is_beat)

            if self.on_frame_callback:
                try:
                    self.on_frame_callback(features, light_state)
                except Exception as cb_exc:
                    logging.debug("Error in on_frame_callback: %s", cb_exc)
        except Exception as exc:
            logging.error("Exception in music sync processing loop: %s", exc)

    def start(self) -> None:
        """Start capturing audio and synchronizing lights."""
        with self._lock:
            if self._running:
                return

            if sd is None:
                raise RuntimeError("sounddevice is not installed. Please install sounddevice and numpy.")

            self._running = True
            try:
                self._stream = sd.InputStream(
                    device=self.device_index,
                    channels=1,
                    samplerate=self.sample_rate,
                    blocksize=self.block_size,
                    callback=self._audio_callback,
                )
                self._stream.start()
                logging.info(
                    "Music synchronizer started (device: %s, targets: %s, mode: %s)",
                    self.device_index,
                    self.target_ips,
                    self.mapper.mode,
                )
            except Exception as exc:
                self._running = False
                if self._stream:
                    try:
                        self._stream.close()
                    except Exception:
                        pass
                    self._stream = None
                raise RuntimeError(f"Could not open audio device: {exc}") from exc

    def stop(self) -> None:
        """Stop capturing audio and release resources."""
        with self._lock:
            if not self._running:
                return
            self._running = False

            if self._stream:
                try:
                    self._stream.stop()
                    self._stream.close()
                except Exception as exc:
                    logging.debug("Error closing audio stream: %s", exc)
                self._stream = None

        self.sender.close()
        logging.info("Music synchronizer stopped.")


def run_cli_visualizer(
    target_ips: List[str],
    mode: str = "spectrum",
    device_index: Optional[int] = None,
    sensitivity: float = 1.0,
    min_brightness: int = 10,
    max_brightness: int = 100,
    duration: Optional[float] = None,
) -> None:
    """Run music synchronizer with live ASCII VU meters in the terminal."""
    last_ui_update = [0.0]

    def on_frame(features: AudioFeatures, state: LightState) -> None:
        now = time.time()
        if now - last_ui_update[0] < 0.08:
            return
        last_ui_update[0] = now

        def bar(val: float, width: int = 10) -> str:
            filled = int(round(max(0.0, min(1.0, val)) * width))
            return "█" * filled + "░" * (width - filled)

        beat_indicator = "⚡ BEAT!" if features.is_beat else "       "
        status_line = (
            f"\r\033[K[VOL {bar(features.volume, 8)}] "
            f"[BASS {bar(features.bass, 8)}] "
            f"[MID {bar(features.mid, 8)}] "
            f"[HI {bar(features.high, 8)}] "
            f"| RGB({state.r:3d},{state.g:3d},{state.b:3d}) DIM {state.dimming:3d}% "
            f"| {beat_indicator}"
        )
        sys.stdout.write(status_line)
        sys.stdout.flush()

    sync = WizMusicSynchronizer(
        target_ips=target_ips,
        device_index=device_index,
        mode=mode,
        sensitivity=sensitivity,
        min_brightness=min_brightness,
        max_brightness=max_brightness,
        on_frame_callback=on_frame,
    )

    print(f"🎵 Starting WiZ Music Synchronizer...")
    print(f"   Targets: {', '.join(target_ips) if target_ips else 'None (Listening only)'}")
    print(f"   Mode: {mode.upper()} | Sensitivity: {sensitivity:.1f}x")
    print(f"   Press Ctrl+C to exit.\n")

    sync.start()
    start_time = time.time()
    try:
        while sync.is_running():
            time.sleep(0.1)
            if duration and (time.time() - start_time) >= duration:
                break
    except KeyboardInterrupt:
        pass
    finally:
        sync.stop()
        print("\n\nStopped music synchronizer.")


def main() -> None:
    """Standalone CLI entry point for wiz_music.py."""
    import argparse
    from wiz_store import load_data

    parser = argparse.ArgumentParser(
        description="WiZ Light Music Synchronizer: Sync WiZ smart lights to real-time audio."
    )
    parser.add_argument(
        "--ip",
        action="append",
        dest="ips",
        help="Target bulb IP address (can specify multiple times).",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Target all discovered lights from saved store.",
    )
    parser.add_argument(
        "--mode",
        choices=SYNC_MODES,
        default="spectrum",
        help=f"Lighting sync mode: {', '.join(SYNC_MODES)} (default: spectrum).",
    )
    parser.add_argument(
        "--device",
        type=int,
        default=None,
        help="Audio input device index (use --list-devices to find).",
    )
    parser.add_argument(
        "--sensitivity",
        type=float,
        default=1.0,
        help="Audio sensitivity multiplier (default: 1.0).",
    )
    parser.add_argument(
        "--min-brightness",
        type=int,
        default=10,
        help="Minimum brightness level (10-100, default: 10).",
    )
    parser.add_argument(
        "--max-brightness",
        type=int,
        default=100,
        help="Maximum brightness level (10-100, default: 100).",
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=None,
        help="Run for this many seconds then exit (default: run until Ctrl+C).",
    )
    parser.add_argument(
        "--list-devices",
        action="store_true",
        help="List available audio input devices and exit.",
    )
    parser.add_argument(
        "--gui",
        action="store_true",
        help="Launch the graphical Music Synchronizer dashboard.",
    )
    parser.add_argument(
        "--system-audio",
        action="store_true",
        help="Capture active system/desktop audio output directly (current music).",
    )

    args = parser.parse_args()

    if args.gui:
        import tkinter as tk
        from wiz_gui import MusicSyncDialog
        store_data = load_data()
        root = tk.Tk()
        root.withdraw()
        dialog = MusicSyncDialog(root, store_data)
        dialog.protocol("WM_DELETE_WINDOW", lambda: (dialog._on_close(), root.destroy()))
        root.mainloop()
        return

    if args.list_devices:
        devices = get_audio_devices()
        print(f"Found {len(devices)} audio input devices:\n")
        for dev in devices:
            default_tag = " [DEFAULT]" if dev["is_default"] else ""
            print(f"  [{dev['index']:2d}] {dev['name']}{default_tag} ({dev['channels']} ch, {int(dev['default_samplerate'])} Hz)")
        return

    device_index = args.device
    if device_index is None or args.system_audio:
        auto_dev = configure_system_audio_monitor()
        if auto_dev is not None:
            device_index = auto_dev
            print(f"Auto-detected system playback monitor (device {device_index})")

    target_ips = args.ips or []
    if not target_ips:
        store_data = load_data()
        saved_devices = store_data.get("devices", {})
        if args.all:
            target_ips = list(saved_devices.keys())
        elif saved_devices:
            # Check reachable bulbs first
            reachable = []
            from wiz_discovery import WizDiscovery
            disco = WizDiscovery()
            for ip in saved_devices:
                if disco.get_device_state(ip) is not None:
                    reachable.append(ip)
            if reachable:
                target_ips = reachable
                print(f"Auto-selected reachable bulb(s): {', '.join(target_ips)}")
            else:
                first_ip = next(iter(saved_devices.keys()))
                target_ips = [first_ip]
                print(f"No bulb IP specified; using saved bulb: {first_ip}")
        else:
            print("Warning: No bulbs found in wiz_data.json or via --ip. Running in visualizer monitor mode.")

    run_cli_visualizer(
        target_ips=target_ips,
        mode=args.mode,
        device_index=device_index,
        sensitivity=args.sensitivity,
        min_brightness=args.min_brightness,
        max_brightness=args.max_brightness,
        duration=args.duration,
    )


if __name__ == "__main__":
    main()
