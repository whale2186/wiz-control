# File: tests/test_wiz_music.py
import json
import logging
import math
import socket
import unittest
from unittest import mock

import numpy as np

import wiz_cli
from wiz_music import (
    AudioAnalyzer,
    AudioFeatures,
    LightMapper,
    LightState,
    SYNC_MODES,
    WizMusicSender,
    WizMusicSynchronizer,
    get_audio_devices,
)


class WizMusicDataClassTests(unittest.TestCase):
    def test_audio_features_defaults(self):
        feat = AudioFeatures()
        self.assertEqual(feat.volume, 0.0)
        self.assertEqual(feat.bass, 0.0)
        self.assertEqual(feat.mid, 0.0)
        self.assertEqual(feat.high, 0.0)
        self.assertFalse(feat.is_beat)
        self.assertEqual(feat.peak, 0.0)

    def test_light_state_defaults(self):
        state = LightState()
        self.assertEqual(state.r, 255)
        self.assertEqual(state.g, 255)
        self.assertEqual(state.b, 255)
        self.assertEqual(state.dimming, 100)
        self.assertTrue(state.state)


class WizMusicAudioDevicesTests(unittest.TestCase):
    def test_get_audio_devices_with_mock_sounddevice(self):
        mock_devices = [
            {"name": "Mic 1", "max_input_channels": 2, "default_samplerate": 48000},
            {"name": "Speakers", "max_input_channels": 0, "default_samplerate": 48000},
            {"name": "Loopback", "max_input_channels": 2, "default_samplerate": 44100},
        ]
        with mock.patch("wiz_music.sd") as mock_sd:
            mock_sd.query_devices.return_value = mock_devices
            mock_sd.default.device = [0, 1]

            devices = get_audio_devices()
            self.assertEqual(len(devices), 2)
            self.assertEqual(devices[0]["name"], "Mic 1")
            self.assertTrue(devices[0]["is_default"])
            self.assertEqual(devices[1]["name"], "Loopback")
            self.assertFalse(devices[1]["is_default"])

    def test_get_audio_devices_without_sounddevice(self):
        with mock.patch("wiz_music.sd", None):
            devices = get_audio_devices()
            self.assertEqual(devices, [])


class WizMusicAudioAnalyzerTests(unittest.TestCase):
    def setUp(self):
        logging.disable(logging.CRITICAL)
        self.sample_rate = 44100
        self.block_size = 2048
        self.analyzer = AudioAnalyzer(
            sample_rate=self.sample_rate,
            block_size=self.block_size,
            sensitivity=1.0,
        )

    def tearDown(self):
        logging.disable(logging.NOTSET)

    def test_empty_audio_returns_zeros(self):
        feat = self.analyzer.analyze(np.zeros(self.block_size))
        self.assertEqual(feat.volume, 0.0)
        self.assertEqual(feat.peak, 0.0)
        self.assertFalse(feat.is_beat)

    def test_frequency_separation_bass(self):
        t = np.linspace(0, self.block_size / self.sample_rate, self.block_size, endpoint=False)
        # 60 Hz pure sine wave (Bass)
        bass_signal = 0.8 * np.sin(2 * np.pi * 60 * t)

        feat = self.analyzer.analyze(bass_signal)
        self.assertGreater(feat.bass, feat.mid)
        self.assertGreater(feat.bass, feat.high)
        self.assertGreater(feat.volume, 0.0)

    def test_frequency_separation_mid(self):
        t = np.linspace(0, self.block_size / self.sample_rate, self.block_size, endpoint=False)
        # 1000 Hz pure sine wave (Mid)
        mid_signal = 0.8 * np.sin(2 * np.pi * 1000 * t)

        feat = self.analyzer.analyze(mid_signal)
        self.assertGreater(feat.mid, feat.bass)
        self.assertGreater(feat.mid, feat.high)

    def test_frequency_separation_high(self):
        t = np.linspace(0, self.block_size / self.sample_rate, self.block_size, endpoint=False)
        # 6000 Hz pure sine wave (High)
        high_signal = 0.8 * np.sin(2 * np.pi * 6000 * t)

        feat = self.analyzer.analyze(high_signal)
        self.assertGreater(feat.high, feat.bass)
        self.assertGreater(feat.high, feat.mid)

    def test_beat_detection_and_cooldown(self):
        t = np.linspace(0, self.block_size / self.sample_rate, self.block_size, endpoint=False)
        quiet_signal = 0.01 * np.sin(2 * np.pi * 60 * t)
        loud_kick = 0.95 * np.sin(2 * np.pi * 60 * t)

        # Feed quiet signals to stabilize AGC
        sim_time = 1.0
        for _ in range(5):
            self.analyzer.analyze(quiet_signal, now=sim_time)
            sim_time += 0.05

        # Trigger sudden loud bass kick after cooldown has elapsed
        sim_time += 0.2
        beat_feat = self.analyzer.analyze(loud_kick, now=sim_time)
        self.assertTrue(beat_feat.is_beat)

        # Immediate next frame (0.01s later) should be debounced by cooldown
        second_feat = self.analyzer.analyze(loud_kick, now=sim_time + 0.01)
        self.assertFalse(second_feat.is_beat)

    def test_sensitivity_adjustment(self):
        self.analyzer.set_sensitivity(2.5)
        self.assertAlmostEqual(self.analyzer.sensitivity, 2.5)


class WizMusicLightMapperTests(unittest.TestCase):
    def setUp(self):
        self.mapper = LightMapper(min_brightness=15, max_brightness=95)

    def test_clamping_ranges(self):
        self.assertEqual(self.mapper._clamp_dimming(5), 15)
        self.assertEqual(self.mapper._clamp_dimming(100), 95)
        self.assertEqual(self.mapper._clamp_dimming(50), 50)
        self.assertEqual(self.mapper._clamp_rgb(-10, 300, 128), (0, 255, 128))

    def test_spectrum_mode(self):
        self.mapper.set_mode("spectrum")
        feat = AudioFeatures(volume=0.8, bass=0.9, mid=0.2, high=0.1, is_beat=False)
        state = self.mapper.map_features(feat)

        self.assertIsInstance(state, LightState)
        self.assertTrue(15 <= state.dimming <= 95)
        self.assertGreater(state.r, state.g)
        self.assertGreater(state.r, state.b)

    def test_beat_pulse_mode(self):
        self.mapper.set_mode("beat_pulse")

        # Non-beat frame decays
        idle_feat = AudioFeatures(volume=0.1, is_beat=False)
        idle_state = self.mapper.map_features(idle_feat)
        self.assertTrue(15 <= idle_state.dimming <= 95)

        # Beat frame jumps to max brightness
        beat_feat = AudioFeatures(volume=0.9, is_beat=True)
        beat_state = self.mapper.map_features(beat_feat)
        self.assertEqual(beat_state.dimming, 95)

    def test_hue_flow_mode(self):
        self.mapper.set_mode("hue_flow")
        feat = AudioFeatures(volume=0.6, is_beat=False)
        state1 = self.mapper.map_features(feat)
        state2 = self.mapper.map_features(feat)

        self.assertTrue(15 <= state1.dimming <= 95)
        self.assertTrue(15 <= state2.dimming <= 95)

    def test_chill_ambient_mode(self):
        self.mapper.set_mode("chill_ambient")
        feat = AudioFeatures(volume=0.5, mid=0.7, is_beat=False)
        state = self.mapper.map_features(feat)

        self.assertTrue(15 <= state.dimming <= 95)
        self.assertTrue(0 <= state.r <= 255)
        self.assertTrue(0 <= state.g <= 255)
        self.assertTrue(0 <= state.b <= 255)

    def test_disco_mode(self):
        self.mapper.set_mode("disco")
        beat_feat = AudioFeatures(volume=0.9, is_beat=True)
        state = self.mapper.map_features(beat_feat)

        self.assertEqual(state.dimming, 95)
        self.assertIn((state.r, state.g, state.b), LightMapper.VIBRANT_PALETTE)


class WizMusicSenderTests(unittest.TestCase):
    def setUp(self):
        logging.disable(logging.CRITICAL)

    def tearDown(self):
        logging.disable(logging.NOTSET)

    @mock.patch("socket.socket")
    def test_send_udp_packet(self, mock_socket_cls):
        mock_sock_instance = mock.MagicMock()
        mock_socket_cls.return_value = mock_sock_instance

        sender = WizMusicSender(min_interval=0.01)
        state = LightState(r=255, g=128, b=64, dimming=80, state=True)
        sent = sender.send(["192.168.1.50"], state, force=True)

        self.assertEqual(sent, 1)
        mock_sock_instance.sendto.assert_called_once()
        args, _ = mock_sock_instance.sendto.call_args
        payload_bytes, addr = args
        self.assertEqual(addr, ("192.168.1.50", 38899))

        payload = json.loads(payload_bytes.decode())
        self.assertEqual(payload["method"], "setPilot")
        self.assertEqual(payload["params"], {"state": True, "dimming": 80, "r": 255, "g": 128, "b": 64})
        sender.close()

    @mock.patch("socket.socket")
    def test_turn_off(self, mock_socket_cls):
        mock_sock_instance = mock.MagicMock()
        mock_socket_cls.return_value = mock_sock_instance

        sender = WizMusicSender()
        sender.turn_off(["192.168.1.50"])

        mock_sock_instance.sendto.assert_called_once()
        args, _ = mock_sock_instance.sendto.call_args
        payload = json.loads(args[0].decode())
        self.assertEqual(payload, {"method": "setPilot", "params": {"state": False}})
        sender.close()


class WizMusicSynchronizerTests(unittest.TestCase):
    def setUp(self):
        logging.disable(logging.CRITICAL)

    def tearDown(self):
        logging.disable(logging.NOTSET)

    @mock.patch("wiz_music.sd")
    def test_lifecycle(self, mock_sd):
        mock_stream = mock.MagicMock()
        mock_sd.InputStream.return_value = mock_stream

        sync = WizMusicSynchronizer(
            target_ips=["192.168.1.20"],
            mode="spectrum",
            sensitivity=1.2,
        )

        self.assertFalse(sync.is_running())
        sync.start()
        self.assertTrue(sync.is_running())
        mock_stream.start.assert_called_once()

        sync.set_mode("beat_pulse")
        self.assertEqual(sync.mapper.mode, "beat_pulse")

        sync.set_sensitivity(1.5)
        self.assertAlmostEqual(sync.analyzer.sensitivity, 1.5)

        sync.stop()
        self.assertFalse(sync.is_running())
        mock_stream.stop.assert_called_once()
        mock_stream.close.assert_called_once()


class WizCliMusicCommandTests(unittest.TestCase):
    def test_parser_has_music_subcommand(self):
        parser = wiz_cli.build_parser()
        args = parser.parse_args(["music", "192.168.1.3", "--mode", "beat_pulse", "--sensitivity", "1.5"])
        self.assertEqual(args.command, "music")
        self.assertEqual(args.target, "192.168.1.3")
        self.assertEqual(args.mode, "beat_pulse")
        self.assertEqual(args.sensitivity, 1.5)

    @mock.patch("wiz_music.run_cli_visualizer")
    def test_run_command_music(self, mock_visualizer):
        fake_data = {
            "rooms": {"101": "Living Room"},
            "devices": {
                "192.168.1.2": {"ip": "192.168.1.2", "moduleName": "Lamp", "roomId": "101"},
            },
            "shortcuts": {},
            "groups": {},
            "favorites": {},
        }
        with mock.patch("wiz_cli.load_data", return_value=fake_data):
            parser = wiz_cli.build_parser()
            args = parser.parse_args(["music", "Lamp", "--mode", "disco", "--duration", "2.0"])
            code = wiz_cli.run_command(args)

            self.assertEqual(code, 0)
            mock_visualizer.assert_called_once_with(
                target_ips=["192.168.1.2"],
                mode="disco",
                device_index=None,
                sensitivity=1.0,
                min_brightness=10,
                max_brightness=100,
                duration=2.0,
            )
