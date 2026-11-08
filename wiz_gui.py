import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox, filedialog
import tkinter.font as tkfont
import copy
import colorsys
import threading
import json
import queue
import time

from wiz_discovery import WizDiscovery
from wiz_music import (
    SYNC_MODES,
    AudioFeatures,
    LightState,
    WizMusicSynchronizer,
    configure_system_audio_monitor,
    get_audio_devices,
)
from wiz_store import (
    DATA_FILE,
    build_device_record,
    build_favorite_record,
    build_group_record,
    describe_group,
    load_data as load_store_data,
    normalize_data,
    rename_generic_room_devices,
    save_data as save_store_data,
)
from wiz_windows_shortcuts import build_cli_shortcut_plan, create_windows_shortcut

BACKGROUND_COLOR = "#07111f"
SURFACE_COLOR = "#0d1b2d"
SURFACE_ALT_COLOR = "#102238"
CARD_COLOR = "#11243a"
CARD_HOVER_COLOR = "#152c46"
ACCENT_COLOR = "#55d6be"
ACCENT_HOVER_COLOR = "#76e4d2"
ACCENT_DARK_COLOR = "#153f42"
SECONDARY_COLOR = "#1a3048"
DANGER_COLOR = "#ef5b5b"
DANGER_HOVER_COLOR = "#ff7474"
SUCCESS_COLOR = "#45d483"
WARNING_COLOR = "#f4bd50"
TEXT_COLOR = "#f5f8fc"
MUTED_TEXT_COLOR = "#91a5bd"
BORDER_COLOR = "#203a55"
LOG_BACKGROUND_COLOR = "#050c16"
PRESET_BUTTON_COLOR = "#183852"
FIELD_COLOR = "#091827"

BRIGHTNESS_MIN = 10
BRIGHTNESS_MAX = 100
TEMPERATURE_MIN = 2200
TEMPERATURE_MAX = 6500
DEFAULT_TEMPERATURE = 3000
DEFAULT_DIMMING = 100

SCENE_OPTIONS = [
    (1, "Ocean"),
    (2, "Romance"),
    (3, "Sunset"),
    (4, "Party"),
    (5, "Fireplace"),
    (6, "Cozy"),
    (7, "Forest"),
    (8, "Pastel"),
    (9, "Wake Up"),
    (10, "Bedtime"),
    (11, "Warm White"),
    (12, "Daylight"),
    (13, "Cool White"),
    (14, "Night Light"),
    (15, "Focus"),
    (16, "Relax"),
    (17, "True Colors"),
    (18, "TV Time"),
    (19, "Plant Growth"),
    (20, "Spring"),
    (21, "Summer"),
    (22, "Fall"),
    (23, "Deep Dive"),
    (24, "Jungle"),
    (25, "Mojito"),
    (26, "Club"),
    (27, "Christmas"),
    (28, "Halloween"),
    (29, "Candlelight"),
    (30, "Golden Hour"),
    (31, "Pulse"),
    (32, "Steampunk"),
]

SCENE_MAP = {scene_id: label for scene_id, label in SCENE_OPTIONS}
SCENE_CHOICES = [f"{scene_id:02d} - {label}" for scene_id, label in SCENE_OPTIONS]

COLOR_PRESETS = [
    {"label": "Warm", "temperature": 2700, "dimming": 75},
    {"label": "Daylight", "temperature": 5000, "dimming": 90},
    {"label": "Ocean", "r": 0, "g": 145, "b": 255, "dimming": 90},
    {"label": "Rose", "r": 255, "g": 56, "b": 124, "dimming": 75},
    {"label": "Violet", "r": 145, "g": 70, "b": 255, "dimming": 80},
]


class ColorPickerDialog(tk.Toplevel):
    """A dependency-free HSV color picker designed for the dark dashboard."""

    GRADIENT_WIDTH = 300
    GRADIENT_HEIGHT = 190
    HUE_WIDTH = 28

    def __init__(self, parent, initial_rgb, on_apply):
        super().__init__(parent)
        self.title("Choose a light color")
        self.configure(bg=SURFACE_COLOR)
        self.resizable(False, False)
        self.transient(parent)
        self.on_apply = on_apply
        self.hue = 0.0
        self.saturation = 1.0
        self.value = 1.0
        self._gradient_image = None
        self._hue_image = None
        self.hex_var = tk.StringVar()
        self.rgb_var = tk.StringVar()

        self._build_ui()
        self._build_hue_strip()
        self._set_from_rgb(*initial_rgb)
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.bind("<Escape>", lambda _event: self.destroy())
        self.bind("<Return>", lambda _event: self._apply())
        self.update_idletasks()
        x = parent.winfo_rootx() + max(20, (parent.winfo_width() - self.winfo_width()) // 2)
        y = parent.winfo_rooty() + max(20, (parent.winfo_height() - self.winfo_height()) // 2)
        self.geometry(f"+{x}+{y}")
        self.grab_set()
        self.focus_force()

    def _build_ui(self):
        shell = tk.Frame(self, bg=SURFACE_COLOR, padx=22, pady=20)
        shell.pack(fill="both", expand=True)

        tk.Label(
            shell,
            text="Choose a color",
            bg=SURFACE_COLOR,
            fg=TEXT_COLOR,
            font=("Segoe UI", 17, "bold"),
        ).grid(row=0, column=0, columnspan=3, sticky="w")
        tk.Label(
            shell,
            text="Drag anywhere in the palette, or enter a HEX value.",
            bg=SURFACE_COLOR,
            fg=MUTED_TEXT_COLOR,
            font=("Segoe UI", 9),
        ).grid(row=1, column=0, columnspan=3, sticky="w", pady=(3, 15))

        self.gradient_canvas = tk.Canvas(
            shell,
            width=self.GRADIENT_WIDTH,
            height=self.GRADIENT_HEIGHT,
            bg=FIELD_COLOR,
            highlightthickness=1,
            highlightbackground=BORDER_COLOR,
            cursor="crosshair",
        )
        self.gradient_canvas.grid(row=2, column=0, sticky="nw")
        self.gradient_canvas.bind("<Button-1>", self._pick_saturation_value)
        self.gradient_canvas.bind("<B1-Motion>", self._pick_saturation_value)

        self.hue_canvas = tk.Canvas(
            shell,
            width=self.HUE_WIDTH,
            height=self.GRADIENT_HEIGHT,
            bg=FIELD_COLOR,
            highlightthickness=1,
            highlightbackground=BORDER_COLOR,
            cursor="sb_v_double_arrow",
        )
        self.hue_canvas.grid(row=2, column=1, sticky="nw", padx=(10, 0))
        self.hue_canvas.bind("<Button-1>", self._pick_hue)
        self.hue_canvas.bind("<B1-Motion>", self._pick_hue)

        side = tk.Frame(shell, bg=SURFACE_COLOR, width=138)
        side.grid(row=2, column=2, sticky="nsew", padx=(18, 0))
        side.grid_propagate(False)

        self.preview = tk.Frame(side, bg="#ffffff", height=72, highlightthickness=1, highlightbackground=BORDER_COLOR)
        self.preview.pack(fill="x")
        self.preview.pack_propagate(False)
        self.preview_label = tk.Label(self.preview, text="Preview", bg="#ffffff", fg="#101828", font=("Segoe UI", 10, "bold"))
        self.preview_label.pack(expand=True)

        tk.Label(side, text="HEX", bg=SURFACE_COLOR, fg=MUTED_TEXT_COLOR, font=("Segoe UI", 8, "bold")).pack(anchor="w", pady=(14, 4))
        hex_entry = tk.Entry(
            side,
            textvariable=self.hex_var,
            bg=FIELD_COLOR,
            fg=TEXT_COLOR,
            insertbackground=TEXT_COLOR,
            selectbackground=ACCENT_DARK_COLOR,
            relief="flat",
            highlightthickness=1,
            highlightbackground=BORDER_COLOR,
            highlightcolor=ACCENT_COLOR,
            font=("Consolas", 11, "bold"),
        )
        hex_entry.pack(fill="x", ipady=7)
        hex_entry.bind("<Return>", self._apply_hex)
        hex_entry.bind("<FocusOut>", self._apply_hex)

        tk.Label(side, textvariable=self.rgb_var, bg=SURFACE_COLOR, fg=MUTED_TEXT_COLOR, font=("Consolas", 9)).pack(anchor="w", pady=(7, 0))

        tk.Label(side, text="QUICK COLORS", bg=SURFACE_COLOR, fg=MUTED_TEXT_COLOR, font=("Segoe UI", 8, "bold")).pack(anchor="w", pady=(15, 6))
        swatches = ["#ff476f", "#ff9f43", "#ffd93d", "#4ee29a", "#38bdf8", "#6c7cff", "#a855f7", "#ffffff"]
        swatch_grid = tk.Frame(side, bg=SURFACE_COLOR)
        swatch_grid.pack(anchor="w")
        for index, color in enumerate(swatches):
            button = tk.Button(
                swatch_grid,
                bg=color,
                activebackground=color,
                width=2,
                height=1,
                relief="flat",
                bd=0,
                cursor="hand2",
                command=lambda value=color: self._set_from_hex(value),
            )
            button.grid(row=index // 4, column=index % 4, padx=(0, 6), pady=(0, 6))

        footer = tk.Frame(shell, bg=SURFACE_COLOR)
        footer.grid(row=3, column=0, columnspan=3, sticky="ew", pady=(18, 0))
        tk.Button(
            footer,
            text="Cancel",
            command=self.destroy,
            bg=SECONDARY_COLOR,
            fg=TEXT_COLOR,
            activebackground=CARD_HOVER_COLOR,
            activeforeground=TEXT_COLOR,
            relief="flat",
            bd=0,
            padx=18,
            pady=9,
            cursor="hand2",
            font=("Segoe UI", 10, "bold"),
        ).pack(side="right")
        tk.Button(
            footer,
            text="Apply to light",
            command=self._apply,
            bg=ACCENT_COLOR,
            fg="#06221d",
            activebackground=ACCENT_HOVER_COLOR,
            activeforeground="#06221d",
            relief="flat",
            bd=0,
            padx=20,
            pady=9,
            cursor="hand2",
            font=("Segoe UI", 10, "bold"),
        ).pack(side="right", padx=(0, 9))

    def _build_hue_strip(self):
        pixels = bytearray()
        for y in range(self.GRADIENT_HEIGHT):
            hue = y / max(1, self.GRADIENT_HEIGHT - 1)
            red, green, blue = colorsys.hsv_to_rgb(hue, 1.0, 1.0)
            rgb = (int(red * 255), int(green * 255), int(blue * 255))
            for _x in range(self.HUE_WIDTH):
                pixels.extend(rgb)
        ppm = f"P6\n{self.HUE_WIDTH} {self.GRADIENT_HEIGHT}\n255\n".encode() + bytes(pixels)
        self._hue_image = tk.PhotoImage(data=ppm, format="PPM")
        self.hue_canvas.create_image(0, 0, image=self._hue_image, anchor="nw")

    def _build_gradient(self):
        pixels = bytearray()
        for y in range(self.GRADIENT_HEIGHT):
            value = 1.0 - (y / max(1, self.GRADIENT_HEIGHT - 1))
            for x in range(self.GRADIENT_WIDTH):
                saturation = x / max(1, self.GRADIENT_WIDTH - 1)
                red, green, blue = colorsys.hsv_to_rgb(self.hue, saturation, value)
                pixels.extend((int(red * 255), int(green * 255), int(blue * 255)))
        ppm = f"P6\n{self.GRADIENT_WIDTH} {self.GRADIENT_HEIGHT}\n255\n".encode() + bytes(pixels)
        self._gradient_image = tk.PhotoImage(data=ppm, format="PPM")
        self.gradient_canvas.delete("gradient")
        self.gradient_canvas.create_image(0, 0, image=self._gradient_image, anchor="nw", tags="gradient")
        self.gradient_canvas.tag_lower("gradient")

    def _set_from_rgb(self, red, green, blue):
        red = max(0, min(255, int(red)))
        green = max(0, min(255, int(green)))
        blue = max(0, min(255, int(blue)))
        self.hue, self.saturation, self.value = colorsys.rgb_to_hsv(red / 255, green / 255, blue / 255)
        self._build_gradient()
        self._update_preview()

    def _set_from_hex(self, value):
        value = value.strip().lstrip("#")
        if len(value) != 6:
            return False
        try:
            channels = tuple(int(value[index:index + 2], 16) for index in (0, 2, 4))
        except ValueError:
            return False
        self._set_from_rgb(*channels)
        return True

    def _apply_hex(self, _event=None):
        self._set_from_hex(self.hex_var.get())

    def _pick_saturation_value(self, event):
        x = max(0, min(self.GRADIENT_WIDTH - 1, event.x))
        y = max(0, min(self.GRADIENT_HEIGHT - 1, event.y))
        self.saturation = x / max(1, self.GRADIENT_WIDTH - 1)
        self.value = 1.0 - (y / max(1, self.GRADIENT_HEIGHT - 1))
        self._update_preview()

    def _pick_hue(self, event):
        y = max(0, min(self.GRADIENT_HEIGHT - 1, event.y))
        self.hue = y / max(1, self.GRADIENT_HEIGHT - 1)
        self._build_gradient()
        self._update_preview()

    def _current_rgb(self):
        red, green, blue = colorsys.hsv_to_rgb(self.hue, self.saturation, self.value)
        return int(round(red * 255)), int(round(green * 255)), int(round(blue * 255))

    def _update_preview(self):
        red, green, blue = self._current_rgb()
        color = f"#{red:02X}{green:02X}{blue:02X}"
        self.hex_var.set(color)
        self.rgb_var.set(f"RGB  {red}, {green}, {blue}")
        self.preview.configure(bg=color)
        self.preview_label.configure(bg=color, fg="#0a1320" if (red * 299 + green * 587 + blue * 114) / 1000 > 150 else "#ffffff")

        x = int(self.saturation * (self.GRADIENT_WIDTH - 1))
        y = int((1.0 - self.value) * (self.GRADIENT_HEIGHT - 1))
        self.gradient_canvas.delete("sv-marker")
        self.gradient_canvas.create_oval(x - 6, y - 6, x + 6, y + 6, outline="white", width=2, tags="sv-marker")
        self.gradient_canvas.create_oval(x - 8, y - 8, x + 8, y + 8, outline="#07111f", width=1, tags="sv-marker")

        hue_y = int(self.hue * (self.GRADIENT_HEIGHT - 1))
        self.hue_canvas.delete("hue-marker")
        self.hue_canvas.create_rectangle(0, hue_y - 2, self.HUE_WIDTH, hue_y + 2, outline="white", width=2, tags="hue-marker")

    def _apply(self):
        red, green, blue = self._current_rgb()
        self.on_apply(red, green, blue)
        self.destroy()


class MusicSyncDialog(tk.Toplevel):
    """Real-time music visualizer & synchronizer dashboard for WiZ lights."""

    MODE_MAP = {
        "Spectrum (Bass=Red, Mid=Green, Treble=Blue)": "spectrum",
        "Beat Pulse (Drop Flash & Smooth Fade)": "beat_pulse",
        "Hue Flow (Rainbow Tempo Drift)": "hue_flow",
        "Chill Ambient (Gentle Breathing Mood)": "chill_ambient",
        "Disco (Party Strobe Jump)": "disco",
    }

    def __init__(self, parent, data):
        super().__init__(parent)
        self.title("WiZ Music Synchronizer")
        self.configure(bg=SURFACE_COLOR)
        self.minsize(620, 640)
        self.resizable(False, False)
        self.transient(parent)
        self.parent = parent
        self.data = data
        self.synchronizer = None
        self._last_ui_frame_time = 0.0

        self._target_var = tk.StringVar()
        self._device_var = tk.StringVar()
        self._mode_var = tk.StringVar(value="Spectrum (Bass=Red, Mid=Green, Treble=Blue)")
        self._sensitivity_var = tk.DoubleVar(value=1.0)
        self._min_brightness_var = tk.IntVar(value=10)
        self._max_brightness_var = tk.IntVar(value=100)
        self._status_var = tk.StringVar(value="Ready to sync lights with audio.")

        self._audio_devices = []
        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.bind("<Escape>", lambda _event: self._on_close())

        self.update_idletasks()
        x = parent.winfo_rootx() + max(20, (parent.winfo_width() - self.winfo_width()) // 2)
        y = parent.winfo_rooty() + max(20, (parent.winfo_height() - self.winfo_height()) // 2)
        self.geometry(f"+{x}+{y}")
        self.focus_force()

    def _build_ui(self):
        shell = tk.Frame(self, bg=SURFACE_COLOR, padx=24, pady=20)
        shell.pack(fill="both", expand=True)

        # Header Frame
        header = tk.Frame(shell, bg=SURFACE_COLOR)
        header.pack(fill="x", pady=(0, 16))
        header.columnconfigure(0, weight=1)

        title_box = tk.Frame(header, bg=SURFACE_COLOR)
        title_box.grid(row=0, column=0, sticky="w")
        tk.Label(
            title_box,
            text="🎵 Music Synchronizer",
            bg=SURFACE_COLOR,
            fg=TEXT_COLOR,
            font=("Segoe UI", 16, "bold"),
        ).pack(anchor="w")
        tk.Label(
            title_box,
            text="Sync WiZ smart lights to music and system audio in real time",
            bg=SURFACE_COLOR,
            fg=MUTED_TEXT_COLOR,
            font=("Segoe UI", 9),
        ).pack(anchor="w", pady=(2, 0))

        self._status_badge = tk.Label(
            header,
            text="● IDLE",
            bg=CARD_COLOR,
            fg=MUTED_TEXT_COLOR,
            font=("Segoe UI", 9, "bold"),
            padx=10,
            pady=4,
        )
        self._status_badge.grid(row=0, column=1, sticky="e")

        # Config Card
        config_card = tk.Frame(shell, bg=CARD_COLOR, padx=16, pady=14, highlightbackground=BORDER_COLOR, highlightthickness=1)
        config_card.pack(fill="x", pady=(0, 14))

        # Target selection
        tk.Label(config_card, text="Target Lights:", bg=CARD_COLOR, fg=MUTED_TEXT_COLOR, font=("Segoe UI", 9, "bold")).grid(
            row=0, column=0, sticky="w", pady=(0, 8)
        )
        target_options = self._build_target_options()
        self._target_combo = ttk.Combobox(
            config_card,
            textvariable=self._target_var,
            values=target_options,
            state="readonly",
            style="App.TCombobox",
            width=36,
        )
        if target_options:
            self._target_combo.current(0)
        self._target_combo.grid(row=0, column=1, columnspan=2, sticky="ew", padx=(10, 0), pady=(0, 8))

        # Audio Input device selection
        tk.Label(config_card, text="Audio Source:", bg=CARD_COLOR, fg=MUTED_TEXT_COLOR, font=("Segoe UI", 9, "bold")).grid(
            row=1, column=0, sticky="w", pady=(0, 8)
        )
        self._refresh_audio_devices()
        device_labels = [
            f"[{d['index']:2d}] {d['name']}{' [SYSTEM AUDIO]' if d.get('is_monitor') else (' (Default)' if d['is_default'] else '')}"
            for d in self._audio_devices
        ]
        if not device_labels:
            device_labels = ["No input devices detected"]
        self._device_combo = ttk.Combobox(
            config_card,
            textvariable=self._device_var,
            values=device_labels,
            state="readonly",
            style="App.TCombobox",
            width=30,
        )
        def_idx = 0
        if getattr(self, "_system_monitor_idx", None) is not None:
            for i, d in enumerate(self._audio_devices):
                if d["index"] == self._system_monitor_idx:
                    def_idx = i
                    break
        else:
            for i, d in enumerate(self._audio_devices):
                if d.get("is_default"):
                    def_idx = i
                    break
        if device_labels and def_idx < len(device_labels):
            self._device_combo.current(def_idx)
        self._device_combo.grid(row=1, column=1, sticky="ew", padx=(10, 6), pady=(0, 8))

        refresh_dev_btn = ttk.Button(config_card, text="↻", width=3, style="Ghost.TButton", command=self._on_refresh_devices)
        refresh_dev_btn.grid(row=1, column=2, sticky="w", pady=(0, 8))

        # Visualizer Mode selection
        tk.Label(config_card, text="Light Mode:", bg=CARD_COLOR, fg=MUTED_TEXT_COLOR, font=("Segoe UI", 9, "bold")).grid(
            row=2, column=0, sticky="w"
        )
        mode_options = list(self.MODE_MAP.keys())
        self._mode_combo = ttk.Combobox(
            config_card,
            textvariable=self._mode_var,
            values=mode_options,
            state="readonly",
            style="App.TCombobox",
            width=36,
        )
        self._mode_combo.current(0)
        self._mode_combo.bind("<<ComboboxSelected>>", self._on_mode_changed)
        self._mode_combo.grid(row=2, column=1, columnspan=2, sticky="ew", padx=(10, 0))

        # Controls & Sliders Card
        sliders_card = tk.Frame(shell, bg=CARD_COLOR, padx=16, pady=12, highlightbackground=BORDER_COLOR, highlightthickness=1)
        sliders_card.pack(fill="x", pady=(0, 14))
        sliders_card.columnconfigure(1, weight=1)

        # Sensitivity Slider
        tk.Label(sliders_card, text="Sensitivity:", bg=CARD_COLOR, fg=TEXT_COLOR, font=("Segoe UI", 9, "bold")).grid(
            row=0, column=0, sticky="w", pady=4
        )
        self.sensitivity_label = tk.Label(sliders_card, text="1.0x", bg=CARD_COLOR, fg=ACCENT_COLOR, font=("Segoe UI", 9, "bold"), width=6)
        self.sensitivity_label.grid(row=0, column=2, sticky="e", padx=(8, 0))
        self.sensitivity_scale = ttk.Scale(
            sliders_card,
            from_=0.2,
            to=3.0,
            variable=self._sensitivity_var,
            command=self._on_sensitivity_changed,
            style="Device.Horizontal.TScale",
        )
        self.sensitivity_scale.grid(row=0, column=1, sticky="ew", padx=10, pady=4)

        # Min Brightness Slider
        tk.Label(sliders_card, text="Min Brightness:", bg=CARD_COLOR, fg=MUTED_TEXT_COLOR, font=("Segoe UI", 9)).grid(
            row=1, column=0, sticky="w", pady=4
        )
        self.min_brightness_label = tk.Label(sliders_card, text="10%", bg=CARD_COLOR, fg=TEXT_COLOR, font=("Segoe UI", 9), width=6)
        self.min_brightness_label.grid(row=1, column=2, sticky="e", padx=(8, 0))
        self.min_brightness_scale = ttk.Scale(
            sliders_card,
            from_=10,
            to=100,
            variable=self._min_brightness_var,
            command=self._on_min_brightness_changed,
            style="Device.Horizontal.TScale",
        )
        self.min_brightness_scale.grid(row=1, column=1, sticky="ew", padx=10, pady=4)

        # Max Brightness Slider
        tk.Label(sliders_card, text="Max Brightness:", bg=CARD_COLOR, fg=MUTED_TEXT_COLOR, font=("Segoe UI", 9)).grid(
            row=2, column=0, sticky="w", pady=4
        )
        self.max_brightness_label = tk.Label(sliders_card, text="100%", bg=CARD_COLOR, fg=TEXT_COLOR, font=("Segoe UI", 9), width=6)
        self.max_brightness_label.grid(row=2, column=2, sticky="e", padx=(8, 0))
        self.max_brightness_scale = ttk.Scale(
            sliders_card,
            from_=10,
            to=100,
            variable=self._max_brightness_var,
            command=self._on_max_brightness_changed,
            style="Device.Horizontal.TScale",
        )
        self.max_brightness_scale.grid(row=2, column=1, sticky="ew", padx=10, pady=4)

        # Real-time Visualizer Canvas Card
        vis_frame = tk.Frame(shell, bg=LOG_BACKGROUND_COLOR, highlightbackground=BORDER_COLOR, highlightthickness=1)
        vis_frame.pack(fill="x", pady=(0, 14))

        self.canvas_width = 570
        self.canvas_height = 140
        self.vis_canvas = tk.Canvas(
            vis_frame,
            width=self.canvas_width,
            height=self.canvas_height,
            bg=LOG_BACKGROUND_COLOR,
            highlightthickness=0,
            bd=0,
        )
        self.vis_canvas.pack(fill="both", expand=True, padx=4, pady=4)
        self._reset_canvas()

        # Action / Control Bar
        action_bar = tk.Frame(shell, bg=SURFACE_COLOR)
        action_bar.pack(fill="x")
        action_bar.columnconfigure(0, weight=1)

        status_lbl = tk.Label(
            action_bar,
            textvariable=self._status_var,
            bg=SURFACE_COLOR,
            fg=MUTED_TEXT_COLOR,
            font=("Segoe UI", 9),
            anchor="w",
        )
        status_lbl.grid(row=0, column=0, sticky="w")

        self._toggle_button = ttk.Button(
            action_bar,
            text="Start Music Sync",
            style="Primary.TButton",
            command=self._toggle_sync,
        )
        self._toggle_button.grid(row=0, column=1, sticky="e")

    def _build_target_options(self):
        options = ["All Lights"]
        devices = self.data.get("devices", {})
        rooms = self.data.get("rooms", {})

        room_groups = {}
        for ip, d in devices.items():
            r_id = str(d.get("roomId", "Unknown"))
            room_groups.setdefault(r_id, []).append((ip, d.get("moduleName", ip)))

        for r_id, dev_list in room_groups.items():
            r_name = rooms.get(r_id, f"Room {r_id}")
            options.append(f"Room: {r_name} ({len(dev_list)} lights)")

        for ip, d in sorted(devices.items()):
            options.append(f"Light: {d.get('moduleName', ip)} ({ip})")

        return options

    def _refresh_audio_devices(self):
        self._audio_devices = get_audio_devices()
        sys_idx = configure_system_audio_monitor()
        self._system_monitor_idx = sys_idx
        if sys_idx is not None:
            for d in self._audio_devices:
                if d["index"] == sys_idx:
                    d["is_monitor"] = True

    def _on_refresh_devices(self):
        self._refresh_audio_devices()
        device_labels = [
            f"[{d['index']:2d}] {d['name']}{' [SYSTEM AUDIO]' if d.get('is_monitor') else (' (Default)' if d['is_default'] else '')}"
            for d in self._audio_devices
        ]
        if not device_labels:
            device_labels = ["No input devices detected"]
        self._device_combo["values"] = device_labels
        if device_labels:
            def_idx = 0
            if self._system_monitor_idx is not None:
                for i, d in enumerate(self._audio_devices):
                    if d["index"] == self._system_monitor_idx:
                        def_idx = i
                        break
            self._device_combo.current(def_idx)

    def _resolve_selected_ips(self):
        choice = self._target_var.get()
        devices = self.data.get("devices", {})
        rooms = self.data.get("rooms", {})

        if choice == "All Lights" or not choice:
            return list(devices.keys())

        if choice.startswith("Room: "):
            room_name_part = choice[6:].split(" (")[0]
            for r_id, r_name in rooms.items():
                if r_name == room_name_part or f"Room {r_id}" == room_name_part:
                    return [ip for ip, d in devices.items() if str(d.get("roomId")) == str(r_id)]
            return [ip for ip, d in devices.items() if f"Room {d.get('roomId')}" == room_name_part]

        if choice.startswith("Light: "):
            if "(" in choice and choice.endswith(")"):
                ip = choice[choice.rfind("(") + 1 : -1]
                return [ip]

        return list(devices.keys())

    def _resolve_selected_device_index(self):
        choice = self._device_var.get()
        if choice.startswith("[") and "]" in choice:
            try:
                idx_str = choice[1 : choice.find("]")].strip()
                return int(idx_str)
            except ValueError:
                pass
        return None

    def _on_mode_changed(self, _event=None):
        if self.synchronizer and self.synchronizer.is_running():
            mode_key = self.MODE_MAP.get(self._mode_var.get(), "spectrum")
            self.synchronizer.set_mode(mode_key)

    def _on_sensitivity_changed(self, val):
        s_val = float(val)
        self.sensitivity_label.config(text=f"{s_val:.1f}x")
        if self.synchronizer and self.synchronizer.is_running():
            self.synchronizer.set_sensitivity(s_val)

    def _on_min_brightness_changed(self, val):
        min_b = int(float(val))
        self.min_brightness_label.config(text=f"{min_b}%")
        max_b = int(self._max_brightness_var.get())
        if min_b > max_b:
            self._max_brightness_var.set(min_b)
            self.max_brightness_label.config(text=f"{min_b}%")
            max_b = min_b
        if self.synchronizer and self.synchronizer.is_running():
            self.synchronizer.set_brightness_range(min_b, max_b)

    def _on_max_brightness_changed(self, val):
        max_b = int(float(val))
        self.max_brightness_label.config(text=f"{max_b}%")
        min_b = int(self._min_brightness_var.get())
        if max_b < min_b:
            self._min_brightness_var.set(max_b)
            self.min_brightness_label.config(text=f"{max_b}%")
            min_b = max_b
        if self.synchronizer and self.synchronizer.is_running():
            self.synchronizer.set_brightness_range(min_b, max_b)

    def _reset_canvas(self):
        self.vis_canvas.delete("all")
        # Equalizer background placeholders
        self.vis_canvas.create_text(35, 122, text="VOL", fill=MUTED_TEXT_COLOR, font=("Segoe UI", 8, "bold"))
        self.vis_canvas.create_text(80, 122, text="BASS", fill="#ef5b5b", font=("Segoe UI", 8, "bold"))
        self.vis_canvas.create_text(125, 122, text="MID", fill="#45d483", font=("Segoe UI", 8, "bold"))
        self.vis_canvas.create_text(170, 122, text="TREBLE", fill="#55d6be", font=("Segoe UI", 8, "bold"))

        # Outline bars
        for x in (25, 70, 115, 160):
            self.vis_canvas.create_rectangle(x, 20, x + 20, 110, outline=BORDER_COLOR, width=1)

        # Beat badge outline
        self.vis_canvas.create_rectangle(220, 48, 310, 84, outline=BORDER_COLOR, width=1, tags="beat_box")
        self.vis_canvas.create_text(265, 66, text="⚡ BEAT", fill=MUTED_TEXT_COLOR, font=("Segoe UI", 10, "bold"), tags="beat_text")

        # Bulb preview circle
        self.vis_canvas.create_oval(440, 20, 520, 100, outline=BORDER_COLOR, width=1, fill="#0d1b2d", tags="bulb_circle")
        self.vis_canvas.create_text(480, 60, text="OFF", fill=MUTED_TEXT_COLOR, font=("Segoe UI", 10, "bold"), tags="bulb_text")
        self.vis_canvas.create_text(480, 122, text="Live Bulb Preview", fill=MUTED_TEXT_COLOR, font=("Segoe UI", 8), tags="bulb_sub")

    def _update_visualizer_canvas(self, features: AudioFeatures, state: LightState):
        try:
            self.vis_canvas.delete("dynamic")

            # Audio frequency EQ bars
            bar_bottom = 110
            bar_height = 90

            # Vol bar
            vol_h = int(features.volume * bar_height)
            if vol_h > 0:
                self.vis_canvas.create_rectangle(25, bar_bottom - vol_h, 45, bar_bottom, fill="#91a5bd", outline="", tags="dynamic")

            # Bass bar (Red)
            bass_h = int(features.bass * bar_height)
            if bass_h > 0:
                self.vis_canvas.create_rectangle(70, bar_bottom - bass_h, 90, bar_bottom, fill="#ef5b5b", outline="", tags="dynamic")

            # Mid bar (Green)
            mid_h = int(features.mid * bar_height)
            if mid_h > 0:
                self.vis_canvas.create_rectangle(115, bar_bottom - mid_h, 135, bar_bottom, fill="#45d483", outline="", tags="dynamic")

            # Treble bar (Cyan)
            high_h = int(features.high * bar_height)
            if high_h > 0:
                self.vis_canvas.create_rectangle(160, bar_bottom - high_h, 180, bar_bottom, fill="#55d6be", outline="", tags="dynamic")

            # Beat Indicator
            if features.is_beat:
                self.vis_canvas.create_rectangle(220, 48, 310, 84, fill=WARNING_COLOR, outline="white", width=2, tags="dynamic")
                self.vis_canvas.create_text(265, 66, text="⚡ BEAT!", fill="#1a1202", font=("Segoe UI", 11, "bold"), tags="dynamic")
            else:
                self.vis_canvas.create_rectangle(220, 48, 310, 84, fill="#11243a", outline=BORDER_COLOR, tags="dynamic")
                self.vis_canvas.create_text(265, 66, text="⚡ BEAT", fill=MUTED_TEXT_COLOR, font=("Segoe UI", 10, "bold"), tags="dynamic")

            # Bulb preview
            hex_color = f"#{state.r:02x}{state.g:02x}{state.b:02x}"
            # Dimming halo based on brightness
            halo_radius = int(35 + (state.dimming / 100.0) * 12)
            self.vis_canvas.create_oval(
                480 - halo_radius,
                60 - halo_radius,
                480 + halo_radius,
                60 + halo_radius,
                fill=hex_color,
                outline="",
                stipple="gray50",
                tags="dynamic",
            )
            # Solid inner bulb
            self.vis_canvas.create_oval(445, 25, 515, 95, fill=hex_color, outline="white", width=2, tags="dynamic")
            self.vis_canvas.create_text(
                480, 60,
                text=f"{state.dimming}%",
                fill="#ffffff" if (state.r * 0.299 + state.g * 0.587 + state.b * 0.114) < 140 else "#000000",
                font=("Segoe UI", 10, "bold"),
                tags="dynamic",
            )
            self.vis_canvas.create_text(
                480, 122,
                text=f"RGB({state.r},{state.g},{state.b})",
                fill=TEXT_COLOR,
                font=("Segoe UI", 8, "bold"),
                tags="dynamic",
            )
        except Exception:
            pass

    def _on_frame(self, features: AudioFeatures, state: LightState):
        now = time.time()
        if now - self._last_ui_frame_time < 0.035:
            return
        self._last_ui_frame_time = now

        try:
            self.after_idle(self._update_visualizer_canvas, features, state)
        except (tk.TclError, RuntimeError):
            pass

    def _toggle_sync(self):
        if self.synchronizer and self.synchronizer.is_running():
            self._stop_sync()
        else:
            self._start_sync()

    def _start_sync(self):
        target_ips = self._resolve_selected_ips()
        if not target_ips:
            messagebox.showwarning("No Target Bulbs", "Please select or discover WiZ lights first.", parent=self)
            return

        device_idx = self._resolve_selected_device_index()
        mode_key = self.MODE_MAP.get(self._mode_var.get(), "spectrum")

        try:
            self.synchronizer = WizMusicSynchronizer(
                target_ips=target_ips,
                device_index=device_idx,
                mode=mode_key,
                sensitivity=self._sensitivity_var.get(),
                min_brightness=self._min_brightness_var.get(),
                max_brightness=self._max_brightness_var.get(),
                on_frame_callback=self._on_frame,
            )
            self.synchronizer.start()
            self._toggle_button.config(text="Stop Music Sync", style="Danger.TButton")
            self._status_var.set(f"Syncing {len(target_ips)} bulb(s) to audio in {self._mode_var.get().split(' ')[0]} mode")
            self._status_badge.config(text="● ACTIVE", foreground=SUCCESS_COLOR)
        except Exception as exc:
            messagebox.showerror("Music Sync Error", f"Failed to start audio capture:\n{exc}", parent=self)

    def _stop_sync(self):
        if self.synchronizer:
            try:
                self.synchronizer.stop()
            except Exception:
                pass
            self.synchronizer = None

        self._toggle_button.config(text="Start Music Sync", style="Primary.TButton")
        self._status_var.set("Stopped. Ready to start.")
        self._status_badge.config(text="● IDLE", foreground=MUTED_TEXT_COLOR)
        self._reset_canvas()

    def _on_close(self):
        self._stop_sync()
        if hasattr(self.parent, "music_sync_dialog"):
            self.parent.music_sync_dialog = None
        self.destroy()


def load_data():
    try:
        return load_store_data(DATA_FILE)
    except json.JSONDecodeError:
        messagebox.showerror("Error", "Data file is corrupted. Loading empty data.")
        return normalize_data(None)


def save_data(data):
    save_store_data(data, DATA_FILE)


class WizGUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("WiZ Home")
        self._set_initial_geometry()
        self.minsize(760, 560)
        self.resizable(True, True)
        self._main_thread = threading.current_thread()
        self._state_lock = threading.RLock()
        self._refresh_lock = threading.Lock()
        self._worker_lock = threading.Lock()
        self._worker_threads = set()
        self._ui_queue = queue.Queue()
        self._closing = False
        self._groups_expanded = False
        self._favorites_expanded = False
        self._discovery_in_progress = False
        self._auto_discovery_job = None
        self._responsive_columns = None
        self.style = ttk.Style(self)
        self.style.theme_use("clam")
        self._configure_style()

        self.discovery = WizDiscovery()
        self.data = load_data()
        self.active_ips = set()
        self.device_status_cache = {ip: None for ip in self.data["devices"]}
        self._refresh_scheduled = False
        self._status_refresh_scheduled = False
        self._status_label_widgets = {}
        self._power_button_widgets = {}
        self.music_sync_dialog = None

        self.auto_discovery_var = tk.BooleanVar(value=True)
        self.create_widgets()
        self.refresh_control_frame()
        self.after(50, self._process_ui_queue)
        self.stop_event = self.update_status_periodically()
        self._auto_discovery_job = self.after(700, self._initial_auto_discovery)

    def _set_initial_geometry(self):
        screen_width = self.winfo_screenwidth()
        screen_height = self.winfo_screenheight()
        width = min(1180, max(900, int(screen_width * 0.86)))
        height = min(900, max(680, int(screen_height * 0.84)))
        width = min(width, max(640, screen_width - 80))
        height = min(height, max(480, screen_height - 100))
        x = max(0, (screen_width - width) // 2)
        y = max(0, (screen_height - height) // 2)
        self.geometry(f"{width}x{height}+{x}+{y}")

    def _configure_style(self):
        self.configure(bg=BACKGROUND_COLOR)
        default_font = tkfont.nametofont("TkDefaultFont")
        default_font.configure(family="Segoe UI", size=10)
        tkfont.nametofont("TkTextFont").configure(family="Segoe UI", size=10)
        tkfont.nametofont("TkFixedFont").configure(family="Consolas", size=10)

        self.heading_font = tkfont.Font(family="Segoe UI", size=22, weight="bold")
        self.subheading_font = tkfont.Font(family="Segoe UI", size=10)
        self.room_title_font = tkfont.Font(family="Segoe UI", size=13, weight="bold")
        self.card_title_font = tkfont.Font(family="Segoe UI", size=11, weight="bold")
        self.metric_font = tkfont.Font(family="Segoe UI", size=22, weight="bold")

        self.style.configure("TFrame", background=BACKGROUND_COLOR)
        self.style.configure("App.TFrame", background=BACKGROUND_COLOR)
        self.style.configure("Toolbar.TFrame", background=BACKGROUND_COLOR)
        self.style.configure("CardContainer.TFrame", background=SURFACE_COLOR)
        self.style.configure("CardHeader.TFrame", background=SURFACE_COLOR)
        self.style.configure("CardBody.TFrame", background=SURFACE_COLOR)
        self.style.configure("Section.TFrame", background=SURFACE_COLOR)
        self.style.configure("SectionHeader.TFrame", background=SURFACE_COLOR)
        self.style.configure("SectionBody.TFrame", background=SURFACE_COLOR)
        self.style.configure("Device.TFrame", background=CARD_COLOR)
        self.style.configure("Log.TFrame", background=LOG_BACKGROUND_COLOR)

        self.style.configure("Heading.TLabel", background=BACKGROUND_COLOR, foreground=TEXT_COLOR, font=self.heading_font)
        self.style.configure("Subheading.TLabel", background=BACKGROUND_COLOR, foreground=MUTED_TEXT_COLOR, font=self.subheading_font)
        self.style.configure("SectionTitle.TLabel", background=BACKGROUND_COLOR, foreground=TEXT_COLOR, font=("Segoe UI", 14, "bold"))
        self.style.configure("CardTitle.TLabel", background=SURFACE_COLOR, foreground=TEXT_COLOR, font=self.room_title_font)
        self.style.configure("Card.TLabel", background=SURFACE_COLOR, foreground=TEXT_COLOR)
        self.style.configure("CardMuted.TLabel", background=SURFACE_COLOR, foreground=MUTED_TEXT_COLOR)
        self.style.configure("DeviceTitle.TLabel", background=CARD_COLOR, foreground=TEXT_COLOR, font=self.card_title_font)
        self.style.configure("Device.TLabel", background=CARD_COLOR, foreground=TEXT_COLOR)
        self.style.configure("DeviceMuted.TLabel", background=CARD_COLOR, foreground=MUTED_TEXT_COLOR)
        self.style.configure("Muted.TLabel", background=BACKGROUND_COLOR, foreground=MUTED_TEXT_COLOR)
        self.style.configure("Badge.TLabel", background=ACCENT_DARK_COLOR, foreground=ACCENT_COLOR, padding=(8, 3), font=("Segoe UI", 8, "bold"))
        self.style.configure("Divider.TSeparator", background=BORDER_COLOR)

        self.style.configure("Primary.TButton", background=ACCENT_COLOR, foreground="#06221d", padding=(14, 8), borderwidth=0, focusthickness=0, font=("Segoe UI", 9, "bold"))
        self.style.map("Primary.TButton", background=[("active", ACCENT_HOVER_COLOR), ("disabled", "#234b4b")], foreground=[("disabled", MUTED_TEXT_COLOR)])
        self.style.configure("Secondary.TButton", background=SECONDARY_COLOR, foreground=TEXT_COLOR, padding=(12, 7), borderwidth=0, font=("Segoe UI", 9, "bold"))
        self.style.map("Secondary.TButton", background=[("active", CARD_HOVER_COLOR), ("disabled", SECONDARY_COLOR)], foreground=[("disabled", MUTED_TEXT_COLOR)])
        self.style.configure("Ghost.TButton", background=BACKGROUND_COLOR, foreground=MUTED_TEXT_COLOR, padding=(10, 7), borderwidth=0)
        self.style.map("Ghost.TButton", background=[("active", SECONDARY_COLOR)], foreground=[("active", TEXT_COLOR)])
        self.style.configure("CardGhost.TButton", background=SURFACE_COLOR, foreground=MUTED_TEXT_COLOR, padding=(9, 6), borderwidth=0)
        self.style.map("CardGhost.TButton", background=[("active", SECONDARY_COLOR)], foreground=[("active", TEXT_COLOR)])
        self.style.configure("DeviceButton.TButton", background=SECONDARY_COLOR, foreground=TEXT_COLOR, padding=(10, 7), borderwidth=0, font=("Segoe UI", 9, "bold"))
        self.style.map("DeviceButton.TButton", background=[("active", CARD_HOVER_COLOR)])
        self.style.configure("Danger.TButton", background=DANGER_COLOR, foreground="white", padding=(10, 6), borderwidth=0)
        self.style.map("Danger.TButton", background=[("active", DANGER_HOVER_COLOR)])
        self.style.configure("Preset.TButton", background=PRESET_BUTTON_COLOR, foreground="#b9ddf4", padding=(10, 5), borderwidth=0, font=("Segoe UI", 8, "bold"))
        self.style.map("Preset.TButton", background=[("active", "#245276")], foreground=[("active", "#ffffff")])
        self.style.configure("Toggle.TButton", background=SURFACE_COLOR, foreground=ACCENT_COLOR, padding=(0, 0), borderwidth=0, font=("Segoe UI", 9, "bold"))
        self.style.map("Toggle.TButton", foreground=[("active", ACCENT_HOVER_COLOR)])

        self.style.configure("App.TEntry", fieldbackground=FIELD_COLOR, foreground=TEXT_COLOR, insertcolor=TEXT_COLOR, padding=(8, 6), bordercolor=BORDER_COLOR, lightcolor=BORDER_COLOR, darkcolor=BORDER_COLOR)
        self.style.configure("Device.TEntry", fieldbackground=CARD_COLOR, foreground=TEXT_COLOR, insertcolor=TEXT_COLOR, padding=(2, 2), borderwidth=0, font=self.card_title_font)
        self.style.configure("Title.TEntry", fieldbackground=FIELD_COLOR, foreground=TEXT_COLOR, font=self.room_title_font, padding=(9, 7), bordercolor=BORDER_COLOR)
        self.style.configure("App.TCombobox", fieldbackground=FIELD_COLOR, background=FIELD_COLOR, foreground=TEXT_COLOR, padding=6, arrowsize=14, bordercolor=BORDER_COLOR)
        self.style.map("App.TCombobox", fieldbackground=[("readonly", FIELD_COLOR)], foreground=[("readonly", TEXT_COLOR)], selectbackground=[("readonly", SECONDARY_COLOR)], selectforeground=[("readonly", TEXT_COLOR)])
        self.option_add("*TCombobox*Listbox.background", FIELD_COLOR)
        self.option_add("*TCombobox*Listbox.foreground", TEXT_COLOR)
        self.option_add("*TCombobox*Listbox.selectBackground", ACCENT_DARK_COLOR)
        self.option_add("*TCombobox*Listbox.selectForeground", TEXT_COLOR)

        self.style.configure("TCheckbutton", background=SURFACE_COLOR, foreground=TEXT_COLOR)
        self.style.configure("Auto.TCheckbutton", background=BACKGROUND_COLOR, foreground=MUTED_TEXT_COLOR, font=("Segoe UI", 9, "bold"))
        self.style.map("Auto.TCheckbutton", background=[("active", BACKGROUND_COLOR)], foreground=[("active", TEXT_COLOR), ("selected", ACCENT_COLOR)])
        self.style.map("TCheckbutton", background=[("active", SURFACE_COLOR)], foreground=[("active", TEXT_COLOR), ("disabled", MUTED_TEXT_COLOR)])
        self.style.configure("Horizontal.TScale", background=SURFACE_COLOR, troughcolor=FIELD_COLOR, bordercolor=SURFACE_COLOR, lightcolor=ACCENT_COLOR, darkcolor=ACCENT_COLOR)
        self.style.configure("Device.Horizontal.TScale", background=CARD_COLOR, troughcolor=FIELD_COLOR, bordercolor=CARD_COLOR, lightcolor=ACCENT_COLOR, darkcolor=ACCENT_COLOR)
        self.style.configure("Vertical.TScrollbar", background=SECONDARY_COLOR, troughcolor=BACKGROUND_COLOR, bordercolor=BACKGROUND_COLOR, arrowcolor=MUTED_TEXT_COLOR)

    def create_widgets(self):
        self.main_container = ttk.Frame(self, style="App.TFrame", padding=(24, 18, 24, 20))
        self.main_container.pack(fill="both", expand=True)

        header = tk.Frame(self.main_container, bg=BACKGROUND_COLOR)
        header.pack(fill="x")
        header.columnconfigure(1, weight=1)

        brand = tk.Canvas(header, width=46, height=46, bg=BACKGROUND_COLOR, highlightthickness=0)
        brand.grid(row=0, column=0, rowspan=2, sticky="w", padx=(0, 13))
        brand.create_oval(3, 3, 43, 43, fill=ACCENT_DARK_COLOR, outline=ACCENT_COLOR, width=1)
        brand.create_oval(15, 12, 31, 28, fill=ACCENT_COLOR, outline="")
        brand.create_rectangle(19, 28, 27, 33, fill=ACCENT_COLOR, outline="")
        brand.create_line(19, 36, 27, 36, fill=ACCENT_COLOR, width=2)

        ttk.Label(header, text="WiZ Home", style="Heading.TLabel").grid(row=0, column=1, sticky="sw")
        self.scan_status_var = tk.StringVar(value="Ready to discover lights on your network")
        ttk.Label(header, textvariable=self.scan_status_var, style="Subheading.TLabel").grid(row=1, column=1, sticky="nw", pady=(1, 0))

        actions = tk.Frame(header, bg=BACKGROUND_COLOR)
        actions.grid(row=0, column=2, rowspan=2, sticky="e")
        ttk.Checkbutton(
            actions,
            text="Auto discover",
            variable=self.auto_discovery_var,
            style="Auto.TCheckbutton",
            command=self._on_auto_discovery_changed,
        ).pack(side="left", padx=(0, 13))
        self.log_toggle = ttk.Button(actions, text="Activity", style="Ghost.TButton", command=self.toggle_logs)
        self.log_toggle.pack(side="left", padx=(0, 8))
        self.music_button = ttk.Button(actions, text="🎵 Music Sync", style="Secondary.TButton", command=self.open_music_sync_dialog)
        self.music_button.pack(side="left", padx=(0, 8))
        self.discover_button = ttk.Button(actions, text="Scan now", style="Primary.TButton", command=self.on_discover_click)
        self.discover_button.pack(side="left")

        self.overview_frame = tk.Frame(self.main_container, bg=BACKGROUND_COLOR)
        self.overview_frame.pack(fill="x", pady=(22, 18))
        for column in range(4):
            self.overview_frame.columnconfigure(column, weight=1, uniform="metrics")

        self.total_devices_var = tk.StringVar(value="0")
        self.online_devices_var = tk.StringVar(value="0")
        self.rooms_count_var = tk.StringVar(value="0")
        self.last_scan_var = tk.StringVar(value="Not scanned yet")
        self._make_stat_card(self.overview_frame, 0, "LIGHTS", self.total_devices_var, "Saved devices")
        self._make_stat_card(self.overview_frame, 1, "ONLINE", self.online_devices_var, "Reachable now", accent=SUCCESS_COLOR)
        self._make_stat_card(self.overview_frame, 2, "ROOMS", self.rooms_count_var, "Detected spaces")
        self._make_stat_card(self.overview_frame, 3, "LAST SCAN", self.last_scan_var, "Automatic every 30 sec", compact=True)

        section_header = tk.Frame(self.main_container, bg=BACKGROUND_COLOR)
        section_header.pack(fill="x", pady=(0, 10))
        ttk.Label(section_header, text="Your spaces", style="SectionTitle.TLabel").pack(side="left")
        ttk.Label(section_header, text="Control every WiZ light from one place", style="Muted.TLabel").pack(side="left", padx=(12, 0), pady=(3, 0))

        self.output_container = ttk.Frame(self.main_container, style="Log.TFrame", padding=12)
        self.output_box = scrolledtext.ScrolledText(self.output_container, width=80, height=7, state="disabled")
        self.output_box.pack(fill="both", expand=True)
        self.output_box.configure(bg=LOG_BACKGROUND_COLOR, fg="#dce8f6", insertbackground=TEXT_COLOR, relief="flat", borderwidth=0, highlightthickness=0, font=("Consolas", 9), padx=8, pady=8)
        self.output_visible = False

        self.control_container = ttk.Frame(self.main_container, style="App.TFrame")
        self.control_container.pack(fill="both", expand=True)
        self.control_canvas = tk.Canvas(self.control_container, borderwidth=0, highlightthickness=0, bg=BACKGROUND_COLOR)
        self.control_scrollbar = ttk.Scrollbar(self.control_container, orient="vertical", command=self.control_canvas.yview)
        self.control_canvas.pack(side="left", fill="both", expand=True)
        self.control_scrollbar.pack(side="right", fill="y")

        self.control_frame = ttk.Frame(self.control_canvas, style="App.TFrame")
        self._control_frame_id = self.control_canvas.create_window((0, 0), window=self.control_frame, anchor="nw")
        self.control_canvas.configure(yscrollcommand=self.control_scrollbar.set)
        self.control_frame.bind("<Configure>", lambda _event: self.control_canvas.configure(scrollregion=self.control_canvas.bbox("all")))
        self.control_canvas.bind("<Configure>", self._on_control_canvas_configure)
        self.bind_all("<MouseWheel>", self._on_mousewheel)
        self.bind_all("<Button-4>", lambda _event: self.control_canvas.yview_scroll(-3, "units"))
        self.bind_all("<Button-5>", lambda _event: self.control_canvas.yview_scroll(3, "units"))

    def _make_stat_card(self, parent, column, eyebrow, value_var, caption, accent=ACCENT_COLOR, compact=False):
        outer = tk.Frame(parent, bg=SURFACE_COLOR, highlightthickness=1, highlightbackground=BORDER_COLOR, padx=16, pady=13)
        outer.grid(row=0, column=column, sticky="nsew", padx=(0 if column == 0 else 6, 0 if column == 3 else 6))
        tk.Label(outer, text=eyebrow, bg=SURFACE_COLOR, fg=MUTED_TEXT_COLOR, font=("Segoe UI", 8, "bold")).pack(anchor="w")
        tk.Label(outer, textvariable=value_var, bg=SURFACE_COLOR, fg=accent, font=("Segoe UI", 13 if compact else 22, "bold"), anchor="w").pack(fill="x", pady=(5, 1))
        tk.Label(outer, text=caption, bg=SURFACE_COLOR, fg=MUTED_TEXT_COLOR, font=("Segoe UI", 8)).pack(anchor="w")

    def _on_control_canvas_configure(self, event):
        self.control_canvas.itemconfigure(self._control_frame_id, width=event.width)
        columns = 2 if event.width >= 980 else 1
        if self._responsive_columns is None:
            self._responsive_columns = columns
        elif columns != self._responsive_columns:
            self._responsive_columns = columns
            self.after(120, self.schedule_refresh)

    def _run_on_ui_thread(self, callback, *args, **kwargs):
        if self._closing:
            return
        self._ui_queue.put((callback, args, kwargs))

    def _process_ui_queue(self):
        while True:
            try:
                callback, args, kwargs = self._ui_queue.get_nowait()
            except queue.Empty:
                break

            if self._closing:
                continue

            try:
                callback(*args, **kwargs)
            except tk.TclError:
                if not self._closing:
                    raise

        if not self._closing:
            self.after(50, self._process_ui_queue)

    def _append_log_message(self, message):
        if self._closing or not hasattr(self, "output_box") or not self.output_box.winfo_exists():
            return
        self.output_box.config(state="normal")
        self.output_box.insert(tk.END, f"{message}\n")
        self.output_box.see(tk.END)
        self.output_box.config(state="disabled")

    def log(self, message):
        self._run_on_ui_thread(self._append_log_message, message)

    def _show_error(self, title, message):
        if self._closing or not self.winfo_exists():
            return
        messagebox.showerror(title, message)

    def _snapshot_data(self):
        with self._state_lock:
            return copy.deepcopy(self.data)

    def _save_data(self):
        try:
            save_data(self._snapshot_data())
            return True
        except Exception as exc:
            self.log(f"Could not save data: {exc}")
            self._run_on_ui_thread(self._show_error, "Error", f"Could not save data: {exc}")
            return False

    def _start_worker(self, target, name):
        def runner():
            try:
                target()
            finally:
                with self._worker_lock:
                    self._worker_threads.discard(threading.current_thread())

        worker = threading.Thread(target=runner, name=name, daemon=True)
        with self._worker_lock:
            self._worker_threads.add(worker)
        worker.start()

    def on_toggle_room(self, room_id, devices, state):
        def toggle():
            refresh_needed = False
            for device in devices:
                ip = device["ip"]
                try:
                    response = self.discovery.send_command(ip, "setState", {"state": state})
                    if response:
                        self.log(f"Device {ip} {'turned on' if state else 'turned off'}.")
                        with self._state_lock:
                            self.device_status_cache[ip] = state
                            self.active_ips.add(ip)
                        refresh_needed = True
                    else:
                        self.log(f"Could not update device {ip}.")
                except Exception as e:
                    self.log(f"Error while controlling device {ip}: {e}")

            if refresh_needed:
                self.schedule_status_refresh()

        self._start_worker(toggle, "toggle-room")

    def on_toggle_device(self, ip, state):
        def toggle():
            try:
                response = self.discovery.send_command(ip, "setState", {"state": state})
                if response:
                    self.log(f"Device {ip} {'turned on' if state else 'turned off'}.")
                    with self._state_lock:
                        self.device_status_cache[ip] = state
                        self.active_ips.add(ip)
                    self.schedule_status_refresh()
                else:
                    self.log(f"Could not update device {ip}.")
                time.sleep(0.2)  # Give the device time to update
            except Exception as e:
                self.log(f"Error while controlling device {ip}: {e}")

        self._start_worker(toggle, "toggle-device")

    def on_toggle_group(self, group_name, group, state):
        devices = self._devices_for_group(group)
        if not devices:
            messagebox.showwarning("Empty Group", f"Group '{group_name}' does not contain any saved devices.")
            return

        def toggle():
            updated_count = 0
            for device in devices:
                ip = device["ip"]
                try:
                    response = self.discovery.send_command(ip, "setState", {"state": state})
                    if response:
                        updated_count += 1
                        with self._state_lock:
                            self.device_status_cache[ip] = state
                            self.active_ips.add(ip)
                    else:
                        self.log(f"Could not update device {ip} in group '{group_name}'.")
                except Exception as exc:
                    self.log(f"Error while controlling device {ip} in group '{group_name}': {exc}")

            if updated_count:
                state_label = "on" if state else "off"
                self.log(f"Group '{group_name}' turned {state_label} ({updated_count} device(s)).")
                self.schedule_status_refresh()

        self._start_worker(toggle, "toggle-group")

    def on_toggle_group_state(self, group_name, group):
        devices = self._devices_for_group(group)
        if not devices:
            messagebox.showwarning("Empty Group", f"Group '{group_name}' does not contain any saved devices.")
            return

        def toggle():
            updated_count = 0
            for device in devices:
                ip = device["ip"]
                try:
                    current_state = self.discovery.get_device_state(ip)
                    if not isinstance(current_state, bool):
                        self.log(f"Could not read current state for {ip} in group '{group_name}'.")
                        continue

                    target_state = not current_state
                    response = self.discovery.send_command(ip, "setState", {"state": target_state})
                    if response:
                        updated_count += 1
                        with self._state_lock:
                            self.device_status_cache[ip] = target_state
                            self.active_ips.add(ip)
                    else:
                        self.log(f"Could not toggle device {ip} in group '{group_name}'.")
                except Exception as exc:
                    self.log(f"Error while toggling device {ip} in group '{group_name}': {exc}")

            if updated_count:
                self.log(f"Group '{group_name}' toggled ({updated_count} device(s)).")
                self.schedule_status_refresh()

        self._start_worker(toggle, "toggle-group-state")

    def on_remove_device(self, ip):
        with self._state_lock:
            record = self.data.get("devices", {}).get(ip, {})
            label = record.get("moduleName", ip) if isinstance(record, dict) else ip
        if not messagebox.askyesno("Remove device", f"Remove '{label}' from this dashboard?\n\nAuto discovery can add it again later."):
            return

        removed = False
        with self._state_lock:
            if ip in self.data["devices"]:
                del self.data["devices"][ip]
                self.active_ips.discard(ip)
                self.device_status_cache.pop(ip, None)
                removed = True

        if removed:
            self._save_data()
            self.log(f"Device {ip} removed.")
            self.schedule_refresh()

    def on_discover_click(self):
        if self._discovery_in_progress or self._closing:
            return
        self._discovery_in_progress = True
        self._set_discovery_ui(True)

        def run_discovery():
            try:
                self.discover_devices()
            finally:
                self._run_on_ui_thread(self._finish_discovery_ui)

        self._start_worker(run_discovery, "discover-devices")

    def _set_discovery_ui(self, scanning):
        if self._closing:
            return
        if scanning:
            self.scan_status_var.set("Scanning the local network for WiZ devices…")
            self.discover_button.configure(text="Scanning…", state="disabled")
        else:
            self.discover_button.configure(text="Scan now", state="normal")

    def _finish_discovery_ui(self):
        self._discovery_in_progress = False
        self._set_discovery_ui(False)
        now = time.strftime("%H:%M:%S")
        self.last_scan_var.set(now)
        with self._state_lock:
            online = len(self.active_ips)
            total = len(self.data.get("devices", {}))
        self.scan_status_var.set(f"Scan complete · {online} of {total} saved light(s) online")
        self._update_dashboard_stats()

    def _initial_auto_discovery(self):
        self._auto_discovery_job = None
        if self._closing:
            return
        if self.auto_discovery_var.get():
            self.on_discover_click()
        self._schedule_next_auto_discovery()

    def _schedule_next_auto_discovery(self):
        if self._closing:
            return
        if self._auto_discovery_job is not None:
            try:
                self.after_cancel(self._auto_discovery_job)
            except tk.TclError:
                pass
        self._auto_discovery_job = self.after(30000, self._auto_discovery_tick)

    def _auto_discovery_tick(self):
        self._auto_discovery_job = None
        if self._closing:
            return
        if self.auto_discovery_var.get() and not self._discovery_in_progress:
            self.on_discover_click()
        self._schedule_next_auto_discovery()

    def _on_auto_discovery_changed(self):
        if self.auto_discovery_var.get():
            self.scan_status_var.set("Auto discovery enabled · scanning every 30 seconds")
            if not self._discovery_in_progress:
                self.on_discover_click()
        else:
            self.scan_status_var.set("Auto discovery paused · use Scan now at any time")
        self._schedule_next_auto_discovery()

    def schedule_refresh(self):
        if self._closing:
            return

        with self._refresh_lock:
            if self._refresh_scheduled:
                return
            self._refresh_scheduled = True

        self._run_on_ui_thread(self._perform_refresh)

    def schedule_status_refresh(self):
        if self._closing:
            return

        with self._refresh_lock:
            if self._status_refresh_scheduled:
                return
            self._status_refresh_scheduled = True

        self._run_on_ui_thread(self._perform_status_refresh)

    def _perform_refresh(self):
        with self._refresh_lock:
            self._refresh_scheduled = False

        if self._closing:
            return
        if self._should_defer_refresh():
            with self._refresh_lock:
                self._refresh_scheduled = True
            self.after(500, self._perform_refresh)
            return
        self.refresh_control_frame()

    def _perform_status_refresh(self):
        with self._refresh_lock:
            self._status_refresh_scheduled = False

        if self._closing:
            return
        self.refresh_status_labels()

    def _should_defer_refresh(self):
        focus_widget = self.focus_get()
        if not focus_widget:
            return False

        try:
            widget_class = focus_widget.winfo_class()
        except tk.TclError:
            return False

        editable_classes = {"Entry", "TEntry", "Spinbox", "TSpinbox", "Text", "TCombobox", "Combobox"}
        return widget_class in editable_classes

    def _get_device_preferences(self, ip):
        with self._state_lock:
            record = self.data["devices"].setdefault(ip, {})
            preferences = record.get("preferences")
            if not isinstance(preferences, dict):
                preferences = {}
                record["preferences"] = preferences
            return preferences

    def _store_device_preferences(self, ip, **updates):
        sanitized = {key: value for key, value in updates.items() if value is not None}
        if not sanitized:
            return

        with self._state_lock:
            preferences = self._get_device_preferences(ip)
            preferences.update(sanitized)

        self._save_data()

    def _get_room_settings(self, room_id):
        with self._state_lock:
            room_settings = self.data.setdefault("room_settings", {})
            settings = room_settings.get(room_id)
            if not isinstance(settings, dict):
                settings = {}
                room_settings[room_id] = settings
            return settings

    def _get_groups(self):
        with self._state_lock:
            groups = self.data.setdefault("groups", {})
            return {
                name: copy.deepcopy(group)
                for name, group in groups.items()
                if isinstance(group, dict)
            }

    def _get_favorites(self):
        with self._state_lock:
            favorites = self.data.setdefault("favorites", {})
            return {
                name: copy.deepcopy(favorite)
                for name, favorite in favorites.items()
                if isinstance(favorite, dict)
            }

    def _devices_for_group(self, group):
        with self._state_lock:
            devices_by_ip = copy.deepcopy(self.data.get("devices", {}))

        devices = []
        seen_ips = set()

        for room_id in group.get("rooms", []):
            for ip, record in devices_by_ip.items():
                if str(record.get("roomId", "Unknown")) != str(room_id):
                    continue
                if ip in seen_ips:
                    continue
                devices.append(record)
                seen_ips.add(ip)

        for target in group.get("devices", []):
            record = devices_by_ip.get(target)
            if not record:
                matches = [
                    candidate
                    for candidate in devices_by_ip.values()
                    if str(candidate.get("moduleName", "")).casefold() == str(target).casefold()
                ]
                record = matches[0] if len(matches) == 1 else None
            if not record:
                continue
            ip = record["ip"]
            if ip in seen_ips:
                continue
            devices.append(record)
            seen_ips.add(ip)

        return devices

    def _format_scene_choice(self, scene_id):
        if scene_id in SCENE_MAP:
            return f"{scene_id:02d} - {SCENE_MAP[scene_id]}"
        return ""

    def _parse_scene_selection(self, value):
        if not value:
            return None
        try:
            scene_text = value.split("-", 1)[0].strip()
            return int(scene_text)
        except (ValueError, AttributeError):
            return None

    def _update_scale_label(self, label_var, value, suffix=""):
        label_var.set(f"{int(float(value))}{suffix}")

    def _clear_focus_on_return(self, event):
        self.focus_set()
        return "break"

    def _save_room_name_on_return(self, event, room_id, name_var):
        self.on_save_room_name(room_id, name_var)
        return "break"

    def toggle_logs(self):
        if self.output_visible:
            self.output_container.pack_forget()
            self.output_visible = False
            self.log_toggle.config(text="Show Logs")
        else:
            self.output_container.pack(fill='both', expand=False, pady=(0, 12), before=self.control_container)
            self.output_visible = True
            self.log_toggle.config(text="Hide Logs")

    def _bind_canvas_scroll(self, _event):
        pass

    def _unbind_canvas_scroll(self, _event):
        pass

    def _on_mousewheel(self, event):
        if event.delta == 0:
            return
        if not self._pointer_within_widget(self.control_container):
            return
        self.control_canvas.yview_scroll(int(-event.delta / 120), "units")

    def _pointer_within_widget(self, widget):
        try:
            pointer_x = self.winfo_pointerx()
            pointer_y = self.winfo_pointery()
            widget_x = widget.winfo_rootx()
            widget_y = widget.winfo_rooty()
            return (
                widget_x <= pointer_x <= widget_x + widget.winfo_width()
                and widget_y <= pointer_y <= widget_y + widget.winfo_height()
            )
        except tk.TclError:
            return False

    def _create_collapsible_section(self, parent, title, collapsed=True):
        container = ttk.Frame(parent, style="Section.TFrame")
        header = ttk.Frame(container, style="SectionHeader.TFrame")
        header.pack(fill="x")
        body = ttk.Frame(container, style="SectionBody.TFrame", padding=(4, 0, 4, 0))

        def show():
            body.pack(fill="x", pady=(8, 0))
            toggle_btn.config(text=f"Hide {title}")

        def hide():
            body.pack_forget()
            toggle_btn.config(text=f"Show {title}")

        def toggle():
            if body.winfo_ismapped():
                hide()
            else:
                show()

        toggle_btn = ttk.Button(header, text="", style="Toggle.TButton", command=toggle)
        toggle_btn.pack(side="left")

        if collapsed:
            hide()
        else:
            show()

        return container, body

    def _build_device_record(self, ip, info):
        with self._state_lock:
            existing = self.data["devices"].get(ip, {})
        return build_device_record(ip, info, existing)

    def _build_view_snapshot(self, include_offline=True):
        with self._state_lock:
            grouped = {}
            active_ips = set(self.active_ips)
            device_status_cache = dict(self.device_status_cache)
            room_names = dict(self.data.get("rooms", {}))
            room_settings = {
                room_id: dict(settings) if isinstance(settings, dict) else {}
                for room_id, settings in self.data.get("room_settings", {}).items()
            }

            for ip, record in self.data["devices"].items():
                if not include_offline and ip not in active_ips:
                    continue
                room_id = record.get("roomId", "Unknown")
                grouped.setdefault(room_id, []).append(copy.deepcopy(record))

        for device_list in grouped.values():
            device_list.sort(key=lambda entry: entry.get("moduleName", ""))

        rooms = dict(sorted(grouped.items(), key=lambda item: item[0]))
        return rooms, active_ips, device_status_cache, room_names, room_settings

    def _format_status(self, ip, active_ips, device_status_cache):
        state = device_status_cache.get(ip)

        if ip not in active_ips:
            return "Offline", "#9ca3af"
        if state is None:
            return "Unknown", "#f59e0b"
        if state:
            return "On", "#10b981"
        return "Off", "#ef4444"

    def refresh_status_labels(self):
        with self._state_lock:
            active_ips = set(self.active_ips)
            device_status_cache = dict(self.device_status_cache)

        stale_ips = []
        for ip, label in self._status_label_widgets.items():
            try:
                if not label.winfo_exists():
                    stale_ips.append(ip)
                    continue
                state_text, state_color = self._format_status(ip, active_ips, device_status_cache)
                status_bg = "#12372c" if state_text == "On" else "#382629" if state_text == "Off" else "#253247"
                label.configure(text=f"● {state_text.upper()}", foreground=state_color, bg=status_bg)
                power = self._power_button_widgets.get(ip)
                if power and power.winfo_exists():
                    is_on = device_status_cache.get(ip) is True
                    power.configure(text="Turn off" if is_on else "Turn on", style="Secondary.TButton" if is_on else "Primary.TButton")
            except tk.TclError:
                stale_ips.append(ip)

        for ip in stale_ips:
            self._status_label_widgets.pop(ip, None)
            self._power_button_widgets.pop(ip, None)
        self._update_dashboard_stats()

    def discover_devices(self):
        self.log("Scanning local network for WiZ devices…")
        try:
            discovered = self.discovery.discover_wiz_devices()
            found_ips = [ip for ip, _ in discovered]
            with self._state_lock:
                active_changed = self.active_ips != set(found_ips)
                self.active_ips = set(found_ips)
                updated = False
                for ip, info in discovered:
                    record = self._build_device_record(ip, info)
                    if self.data["devices"].get(ip) != record:
                        updated = True
                    self.data["devices"][ip] = record
                    self.device_status_cache.setdefault(ip, None)

            for ip, _info in discovered:
                try:
                    state = self.discovery.get_device_state(ip)
                except Exception as exc:
                    self.log(f"Could not read initial status from {ip}: {exc}")
                    state = None
                with self._state_lock:
                    self.device_status_cache[ip] = state

            if discovered:
                self.log(f"Found {len(discovered)} WiZ device(s).")
                rooms, _, _, room_names, _ = self._build_view_snapshot(include_offline=False)
                for room_id, devices_in_room in rooms.items():
                    room_name = room_names.get(room_id, f"Room {room_id}")
                    self.log(f"  {room_name}: {len(devices_in_room)} light(s)")
            else:
                self.log("No WiZ devices answered this scan. Saved devices remain available as offline cards.")

            if updated:
                self._save_data()
            if updated or active_changed:
                self.schedule_refresh()
            else:
                self.schedule_status_refresh()
        except Exception as exc:
            self.log(f"Discovery error: {exc}")

    def refresh_control_frame(self):
        for widget in self.control_frame.winfo_children():
            widget.destroy()
        self._status_label_widgets = {}
        self._power_button_widgets = {}

        rooms, active_ips, device_status_cache, room_names, room_settings_map = self._build_view_snapshot(include_offline=True)
        groups = self._get_groups()
        favorites = self._get_favorites()
        self._update_dashboard_stats()

        self._render_favorites_editor(rooms, room_names, groups, favorites)
        self._render_group_editor(rooms, room_names, groups)

        if not rooms:
            empty = tk.Frame(self.control_frame, bg=SURFACE_COLOR, highlightthickness=1, highlightbackground=BORDER_COLOR, padx=28, pady=34)
            empty.pack(fill="x", padx=2, pady=8)
            icon = tk.Canvas(empty, width=64, height=64, bg=SURFACE_COLOR, highlightthickness=0)
            icon.pack()
            icon.create_oval(4, 4, 60, 60, fill=ACCENT_DARK_COLOR, outline=ACCENT_COLOR)
            icon.create_oval(22, 17, 42, 39, fill=ACCENT_COLOR, outline="")
            icon.create_rectangle(27, 39, 37, 45, fill=ACCENT_COLOR, outline="")
            tk.Label(empty, text="No WiZ lights found yet", bg=SURFACE_COLOR, fg=TEXT_COLOR, font=("Segoe UI", 15, "bold")).pack(pady=(12, 4))
            tk.Label(empty, text="Keep your lights and this computer on the same Wi-Fi network, then scan again.", bg=SURFACE_COLOR, fg=MUTED_TEXT_COLOR, font=("Segoe UI", 10)).pack()
            ttk.Button(empty, text="Scan for devices", style="Primary.TButton", command=self.on_discover_click).pack(pady=(18, 0))
            return
        self._render_room_cards(rooms, active_ips, device_status_cache, room_names, room_settings_map)

    def _update_dashboard_stats(self):
        if self._closing or not hasattr(self, "total_devices_var"):
            return
        with self._state_lock:
            total = len(self.data.get("devices", {}))
            online = len(self.active_ips.intersection(self.data.get("devices", {}).keys()))
            room_ids = {str(record.get("roomId", "Unknown")) for record in self.data.get("devices", {}).values()}
        self.total_devices_var.set(str(total))
        self.online_devices_var.set(str(online))
        self.rooms_count_var.set(str(len(room_ids)))

    def _render_room_cards(self, rooms, active_ips, device_status_cache, room_names, room_settings_map):
        columns = self._responsive_columns or (2 if self.winfo_width() >= 1180 else 1)
        for room_id, devices_in_room in rooms.items():
            room_name = room_names.get(room_id, f"Room {room_id}")
            room_settings = room_settings_map.get(room_id, {})
            device_ips = tuple(device["ip"] for device in devices_in_room)
            online_count = sum(1 for device in devices_in_room if device["ip"] in active_ips)

            room_card = tk.Frame(
                self.control_frame,
                bg=SURFACE_COLOR,
                highlightbackground=BORDER_COLOR,
                highlightcolor=BORDER_COLOR,
                highlightthickness=1,
                bd=0,
                padx=16,
                pady=15,
            )
            room_card.pack(fill="x", pady=(0, 14), padx=2)

            header = tk.Frame(room_card, bg=SURFACE_COLOR)
            header.pack(fill="x")
            header.columnconfigure(0, weight=1)

            title_area = tk.Frame(header, bg=SURFACE_COLOR)
            title_area.grid(row=0, column=0, sticky="w")
            name_var = tk.StringVar(value=room_name)
            name_entry = tk.Entry(
                title_area,
                textvariable=name_var,
                width=max(15, min(28, len(room_name) + 5)),
                bg=FIELD_COLOR,
                fg=TEXT_COLOR,
                insertbackground=TEXT_COLOR,
                selectbackground=ACCENT_DARK_COLOR,
                selectforeground=TEXT_COLOR,
                relief="flat",
                bd=0,
                highlightthickness=1,
                highlightbackground=BORDER_COLOR,
                highlightcolor=ACCENT_COLOR,
                font=("Segoe UI", 12, "bold"),
            )
            name_entry.pack(side="left", ipady=7)
            name_entry.bind("<Return>", lambda event, rid=room_id, var=name_var: self._save_room_name_on_return(event, rid, var))
            ttk.Label(title_area, text=f"ROOM {room_id}", style="Badge.TLabel").pack(side="left", padx=(10, 0))
            tk.Label(
                title_area,
                text=f"{online_count}/{len(devices_in_room)} online",
                bg=SURFACE_COLOR,
                fg=SUCCESS_COLOR if online_count else MUTED_TEXT_COLOR,
                font=("Segoe UI", 9, "bold"),
            ).pack(side="left", padx=(10, 0))

            room_actions = tk.Frame(header, bg=SURFACE_COLOR)
            room_actions.grid(row=0, column=1, sticky="e")
            ttk.Button(room_actions, text="Save name", style="CardGhost.TButton", command=lambda rid=room_id, var=name_var: self.on_save_room_name(rid, var)).pack(side="left", padx=(0, 6))
            ttk.Button(room_actions, text="All off", style="Secondary.TButton", command=lambda rid=room_id, devices=devices_in_room: self.on_toggle_room(rid, devices, False)).pack(side="left", padx=(0, 6))
            ttk.Button(room_actions, text="All on", style="Primary.TButton", command=lambda rid=room_id, devices=devices_in_room: self.on_toggle_room(rid, devices, True)).pack(side="left")

            tools = tk.Frame(room_card, bg=SURFACE_ALT_COLOR, highlightthickness=1, highlightbackground=BORDER_COLOR, padx=11, pady=9)
            tools.pack(fill="x", pady=(13, 13))
            tk.Label(tools, text="SCENE", bg=SURFACE_ALT_COLOR, fg=MUTED_TEXT_COLOR, font=("Segoe UI", 8, "bold")).pack(side="left")
            scene_var = tk.StringVar(value=self._format_scene_choice(room_settings.get("sceneId")))
            scene_combo = ttk.Combobox(tools, values=SCENE_CHOICES, textvariable=scene_var, width=21, state="readonly", style="App.TCombobox")
            scene_combo.pack(side="left", padx=(8, 10))
            speed_value = room_settings.get("sceneSpeed", 100)
            try:
                speed_value = max(20, min(200, int(speed_value)))
            except (TypeError, ValueError):
                speed_value = 100
            speed_var = tk.IntVar(value=speed_value)
            tk.Label(tools, text="Speed", bg=SURFACE_ALT_COLOR, fg=MUTED_TEXT_COLOR, font=("Segoe UI", 9)).pack(side="left")
            speed_spin = tk.Spinbox(tools, from_=20, to=200, textvariable=speed_var, width=4, bg=FIELD_COLOR, fg=TEXT_COLOR, buttonbackground=SECONDARY_COLOR, relief="flat", bd=0, highlightthickness=1, highlightbackground=BORDER_COLOR, insertbackground=TEXT_COLOR)
            speed_spin.pack(side="left", padx=(7, 9), ipady=4)
            ttk.Button(tools, text="Apply scene", style="DeviceButton.TButton", command=lambda rid=room_id, ips=device_ips, svar=scene_var, spd=speed_var: self.on_apply_room_scene(rid, ips, svar, spd)).pack(side="left")

            devices_grid = tk.Frame(room_card, bg=SURFACE_COLOR)
            devices_grid.pack(fill="x")
            for column in range(columns):
                devices_grid.columnconfigure(column, weight=1, uniform=f"room-{room_id}")

            for index, device in enumerate(devices_in_room):
                device_card = self._build_device_card(devices_grid, device, active_ips, device_status_cache)
                row, column = divmod(index, columns)
                device_card.grid(row=row, column=column, sticky="nsew", padx=(0 if column == 0 else 7, 0 if column == columns - 1 else 7), pady=(0, 12))

    def _build_device_card(self, parent, device, active_ips, device_status_cache):
        ip = device["ip"]
        module_name = device.get("moduleName", f"Device {ip}")
        preferences = device.get("preferences", {}) if isinstance(device.get("preferences"), dict) else {}

        def clamp(value, minimum, maximum, fallback):
            try:
                return max(minimum, min(maximum, int(float(value))))
            except (TypeError, ValueError):
                return fallback

        brightness_value = clamp(preferences.get("dimming", DEFAULT_DIMMING), BRIGHTNESS_MIN, BRIGHTNESS_MAX, DEFAULT_DIMMING)
        temperature_value = clamp(preferences.get("temperature", DEFAULT_TEMPERATURE), TEMPERATURE_MIN, TEMPERATURE_MAX, DEFAULT_TEMPERATURE)
        red_value = clamp(preferences.get("r", 255), 0, 255, 255)
        green_value = clamp(preferences.get("g", 210), 0, 255, 210)
        blue_value = clamp(preferences.get("b", 120), 0, 255, 120)
        current_hex = self._rgb_to_hex(red_value, green_value, blue_value)

        card = tk.Frame(parent, bg=CARD_COLOR, highlightthickness=1, highlightbackground=BORDER_COLOR, padx=14, pady=13)
        card.columnconfigure(0, weight=1)

        top = tk.Frame(card, bg=CARD_COLOR)
        top.grid(row=0, column=0, sticky="ew")
        top.columnconfigure(1, weight=1)

        bulb = tk.Canvas(top, width=44, height=44, bg=CARD_COLOR, highlightthickness=0)
        bulb.grid(row=0, column=0, rowspan=2, sticky="w", padx=(0, 10))
        bulb.create_oval(2, 2, 42, 42, fill=ACCENT_DARK_COLOR, outline=BORDER_COLOR)
        bulb.create_oval(14, 9, 30, 27, fill=current_hex, outline="")
        bulb.create_rectangle(18, 27, 26, 32, fill=current_hex, outline="")
        bulb.create_line(18, 35, 26, 35, fill=MUTED_TEXT_COLOR, width=2)

        device_name_var = tk.StringVar(value=module_name)
        name_entry = tk.Entry(
            top,
            textvariable=device_name_var,
            bg=CARD_COLOR,
            fg=TEXT_COLOR,
            insertbackground=TEXT_COLOR,
            selectbackground=ACCENT_DARK_COLOR,
            selectforeground=TEXT_COLOR,
            relief="flat",
            bd=0,
            highlightthickness=0,
            font=("Segoe UI", 11, "bold"),
        )
        name_entry.grid(row=0, column=1, sticky="ew")
        name_entry.bind("<Return>", lambda event, target_ip=ip, var=device_name_var: self._save_device_name_on_return(event, target_ip, var))
        ttk.Label(top, text=ip, style="DeviceMuted.TLabel").grid(row=1, column=1, sticky="w", pady=(2, 0))

        state_text, state_color = self._format_status(ip, active_ips, device_status_cache)
        status_bg = "#12372c" if state_text == "On" else "#382629" if state_text == "Off" else "#253247"
        status = tk.Label(top, text=f"● {state_text.upper()}", bg=status_bg, fg=state_color, padx=9, pady=4, font=("Segoe UI", 8, "bold"))
        status.grid(row=0, column=2, rowspan=2, padx=(10, 0), sticky="e")
        self._status_label_widgets[ip] = status

        state_is_on = device_status_cache.get(ip) is True
        power_button = ttk.Button(
            card,
            text="Turn off" if state_is_on else "Turn on",
            style="Secondary.TButton" if state_is_on else "Primary.TButton",
            command=lambda target_ip=ip: self.on_toggle_device(target_ip, not bool(self.device_status_cache.get(target_ip, False))),
        )
        power_button.grid(row=1, column=0, sticky="ew", pady=(13, 11))
        self._power_button_widgets[ip] = power_button

        brightness_var = tk.IntVar(value=brightness_value)
        brightness_label_var = tk.StringVar(value=f"{brightness_value}%")
        brightness_header = tk.Frame(card, bg=CARD_COLOR)
        brightness_header.grid(row=2, column=0, sticky="ew")
        tk.Label(brightness_header, text="Brightness", bg=CARD_COLOR, fg=TEXT_COLOR, font=("Segoe UI", 9, "bold")).pack(side="left")
        tk.Label(brightness_header, textvariable=brightness_label_var, bg=CARD_COLOR, fg=ACCENT_COLOR, font=("Segoe UI", 9, "bold")).pack(side="right")
        brightness_scale = ttk.Scale(card, from_=BRIGHTNESS_MIN, to=BRIGHTNESS_MAX, variable=brightness_var, style="Device.Horizontal.TScale", command=lambda value, label=brightness_label_var: self._update_scale_label(label, value, "%"))
        brightness_scale.grid(row=3, column=0, sticky="ew", pady=(3, 11))
        brightness_scale.bind("<ButtonRelease-1>", lambda _event, target_ip=ip, var=brightness_var: self.on_apply_brightness(target_ip, var))

        color_panel = tk.Frame(card, bg=SURFACE_ALT_COLOR, highlightthickness=1, highlightbackground=BORDER_COLOR, padx=10, pady=9)
        color_panel.grid(row=4, column=0, sticky="ew")
        color_panel.columnconfigure(1, weight=1)
        red_var = tk.IntVar(value=red_value)
        green_var = tk.IntVar(value=green_value)
        blue_var = tk.IntVar(value=blue_value)
        color_hex_var = tk.StringVar(value=current_hex.upper())
        swatch = tk.Button(color_panel, bg=current_hex, activebackground=current_hex, width=4, height=2, relief="flat", bd=0, cursor="hand2")
        swatch.grid(row=0, column=0, rowspan=2, padx=(0, 10))
        tk.Label(color_panel, text="Color", bg=SURFACE_ALT_COLOR, fg=TEXT_COLOR, font=("Segoe UI", 9, "bold")).grid(row=0, column=1, sticky="sw")
        tk.Label(color_panel, textvariable=color_hex_var, bg=SURFACE_ALT_COLOR, fg=MUTED_TEXT_COLOR, font=("Consolas", 9)).grid(row=1, column=1, sticky="nw")
        picker_command = lambda: self._open_device_color_picker(ip, brightness_var, red_var, green_var, blue_var, color_hex_var, swatch, bulb)
        swatch.configure(command=picker_command)
        ttk.Button(color_panel, text="Choose color", style="DeviceButton.TButton", command=picker_command).grid(row=0, column=2, rowspan=2, sticky="e")

        temperature_var = tk.IntVar(value=temperature_value)
        temperature_label_var = tk.StringVar(value=f"{temperature_value}K")
        white_row = tk.Frame(card, bg=CARD_COLOR)
        white_row.grid(row=5, column=0, sticky="ew", pady=(12, 0))
        white_row.columnconfigure(1, weight=1)
        tk.Label(white_row, text="White", bg=CARD_COLOR, fg=TEXT_COLOR, font=("Segoe UI", 9, "bold")).grid(row=0, column=0, sticky="w")
        ttk.Scale(white_row, from_=TEMPERATURE_MIN, to=TEMPERATURE_MAX, variable=temperature_var, style="Device.Horizontal.TScale", command=lambda value, label=temperature_label_var: self._update_scale_label(label, value, "K")).grid(row=0, column=1, sticky="ew", padx=(8, 8))
        tk.Label(white_row, textvariable=temperature_label_var, bg=CARD_COLOR, fg=MUTED_TEXT_COLOR, font=("Segoe UI", 8), width=6).grid(row=0, column=2)
        ttk.Button(white_row, text="Apply", style="DeviceButton.TButton", command=lambda target_ip=ip, b=brightness_var, t=temperature_var: self.on_apply_white(target_ip, b, t)).grid(row=0, column=3, padx=(8, 0))

        preset_row = tk.Frame(card, bg=CARD_COLOR)
        preset_row.grid(row=6, column=0, sticky="w", pady=(11, 0))
        red_label = tk.StringVar(value=str(red_value))
        green_label = tk.StringVar(value=str(green_value))
        blue_label = tk.StringVar(value=str(blue_value))
        for preset in COLOR_PRESETS:
            ttk.Button(
                preset_row,
                text=preset["label"],
                style="Preset.TButton",
                command=lambda chosen=preset: self._apply_card_preset(ip, chosen, brightness_var, temperature_var, red_var, green_var, blue_var, brightness_label_var, temperature_label_var, red_label, green_label, blue_label, color_hex_var, swatch, bulb),
            ).pack(side="left", padx=(0, 5))

        details_container, details = self._create_collapsible_section(card, "More controls", collapsed=True)
        details_container.grid(row=7, column=0, sticky="ew", pady=(12, 0))
        shortcut_var = tk.StringVar(value=module_name)
        shortcut_row = tk.Frame(details, bg=SURFACE_COLOR)
        shortcut_row.pack(fill="x")
        ttk.Entry(shortcut_row, textvariable=shortcut_var, width=20, style="App.TEntry").pack(side="left", fill="x", expand=True)
        ttk.Button(shortcut_row, text="Save on", style="CardGhost.TButton", command=lambda var=shortcut_var, target_ip=ip: self.on_save_state_shortcut(var, "device", target_ip, True)).pack(side="left", padx=(6, 0))
        ttk.Button(shortcut_row, text="Save off", style="CardGhost.TButton", command=lambda var=shortcut_var, target_ip=ip: self.on_save_state_shortcut(var, "device", target_ip, False)).pack(side="left", padx=(4, 0))
        action_row = tk.Frame(details, bg=SURFACE_COLOR)
        action_row.pack(fill="x", pady=(8, 0))
        ttk.Button(action_row, text="Save device name", style="CardGhost.TButton", command=lambda target_ip=ip, var=device_name_var: self.on_save_device_name(target_ip, var)).pack(side="left")
        ttk.Button(action_row, text="Remove device", style="Danger.TButton", command=lambda target_ip=ip: self.on_remove_device(target_ip)).pack(side="right")
        return card

    @staticmethod
    def _rgb_to_hex(red, green, blue):
        return f"#{max(0, min(255, int(red))):02x}{max(0, min(255, int(green))):02x}{max(0, min(255, int(blue))):02x}"

    def _open_device_color_picker(self, ip, brightness_var, red_var, green_var, blue_var, hex_var, swatch, bulb_canvas):
        initial = (red_var.get(), green_var.get(), blue_var.get())

        def apply(red, green, blue):
            red_var.set(red)
            green_var.set(green)
            blue_var.set(blue)
            color = self._rgb_to_hex(red, green, blue)
            hex_var.set(color.upper())
            swatch.configure(bg=color, activebackground=color)
            bulb_canvas.itemconfigure(2, fill=color)
            bulb_canvas.itemconfigure(3, fill=color)
            self.on_apply_color(ip, brightness_var, red_var, green_var, blue_var)

        ColorPickerDialog(self, initial, apply)

    def _apply_card_preset(self, ip, preset, brightness_var, temperature_var, red_var, green_var, blue_var, brightness_label, temperature_label, red_label, green_label, blue_label, hex_var, swatch, bulb_canvas):
        self.on_apply_preset(ip, preset, brightness_var, temperature_var, red_var, green_var, blue_var, brightness_label, temperature_label, red_label, green_label, blue_label)
        if "temperature" not in preset:
            color = self._rgb_to_hex(red_var.get(), green_var.get(), blue_var.get())
            hex_var.set(color.upper())
            swatch.configure(bg=color, activebackground=color)
            bulb_canvas.itemconfigure(2, fill=color)
            bulb_canvas.itemconfigure(3, fill=color)

    def _favorite_target_options(self, target_type, rooms, room_names, groups):
        options = []
        if target_type == "device":
            devices = [
                device
                for devices_in_room in rooms.values()
                for device in devices_in_room
            ]
            for device in sorted(devices, key=lambda entry: entry.get("moduleName", "").casefold()):
                ip = device["ip"]
                label = f"{device.get('moduleName', f'Device {ip}')} ({ip})"
                options.append((label, ip))
        elif target_type == "room":
            for room_id, devices_in_room in rooms.items():
                room_name = room_names.get(room_id, f"Room {room_id}")
                options.append((f"{room_name} (ID {room_id}, {len(devices_in_room)} light(s))", room_id))
        else:
            for group_name in sorted(groups):
                options.append((group_name, group_name))
        return options

    def _favorite_action_label(self, favorite):
        if favorite.get("action") == "toggle":
            return "toggle"
        return "on" if favorite.get("state") else "off"

    def _describe_favorite(self, favorite, room_names, groups, devices):
        target_type = favorite.get("target_type", "unknown")
        target = favorite.get("target", "")
        if target_type == "device":
            target_label = devices.get(target, {}).get("moduleName", target)
        elif target_type == "room":
            target_label = room_names.get(target, f"Room {target}")
        elif target_type == "group":
            target_label = groups.get(target, {}).get("label", target)
        else:
            target_label = target
        return f"{target_type}: {target_label} | {self._favorite_action_label(favorite)}"

    def _render_favorites_editor(self, rooms, room_names, groups, favorites):
        card = tk.Frame(
            self.control_frame,
            bg=SURFACE_COLOR,
            bd=0,
            highlightbackground=BORDER_COLOR,
            highlightcolor=BORDER_COLOR,
            highlightthickness=1,
        )
        card.pack(fill="x", pady=8, padx=4)

        frame = ttk.Frame(card, style="CardContainer.TFrame", padding=12)
        frame.pack(fill="both", expand=True)
        frame.columnconfigure(0, weight=1)

        header = ttk.Frame(frame, style="CardHeader.TFrame")
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(1, weight=1)
        ttk.Label(header, text="Favorites", style="CardTitle.TLabel").grid(row=0, column=0, sticky="w")
        summary = f"{len(favorites)} saved" if favorites else "No saved favorites"
        ttk.Label(header, text=summary, style="CardMuted.TLabel").grid(row=0, column=1, sticky="w", padx=(10, 0))
        toggle_text = "Hide Favorites" if self._favorites_expanded else "Show Favorites"
        ttk.Button(
            header,
            text=toggle_text,
            style="Ghost.TButton",
            command=self.toggle_favorites_editor,
        ).grid(row=0, column=2, sticky="e")

        if not self._favorites_expanded:
            return

        form_frame = ttk.Frame(frame, style="CardBody.TFrame")
        form_frame.grid(row=1, column=0, sticky="ew", pady=(10, 8))
        form_frame.columnconfigure(5, weight=1)

        favorite_name_var = tk.StringVar(value="Favorite 1")
        target_type_var = tk.StringVar(value="group")
        target_var = tk.StringVar()
        action_var = tk.StringVar(value="Toggle")
        target_lookup = {}

        ttk.Label(form_frame, text="Name", style="CardMuted.TLabel").grid(row=0, column=0, sticky="w")
        favorite_name_entry = ttk.Entry(form_frame, textvariable=favorite_name_var, width=22, style="App.TEntry")
        favorite_name_entry.grid(row=0, column=1, sticky="w", padx=(6, 10))
        favorite_name_entry.bind("<Return>", self._clear_focus_on_return)

        ttk.Label(form_frame, text="Target", style="CardMuted.TLabel").grid(row=0, column=2, sticky="w")
        target_type_combo = ttk.Combobox(
            form_frame,
            values=("device", "room", "group"),
            textvariable=target_type_var,
            width=8,
            state="readonly",
            style="App.TCombobox",
        )
        target_type_combo.grid(row=0, column=3, sticky="w", padx=(6, 6))

        target_combo = ttk.Combobox(
            form_frame,
            values=(),
            textvariable=target_var,
            width=34,
            state="readonly",
            style="App.TCombobox",
        )
        target_combo.grid(row=0, column=4, sticky="w", padx=(0, 10))

        ttk.Label(form_frame, text="Action", style="CardMuted.TLabel").grid(row=0, column=5, sticky="e")
        action_combo = ttk.Combobox(
            form_frame,
            values=("Toggle", "On", "Off"),
            textvariable=action_var,
            width=8,
            state="readonly",
            style="App.TCombobox",
        )
        action_combo.grid(row=0, column=6, sticky="e", padx=(6, 0))

        def update_targets(_event=None):
            target_lookup.clear()
            options = self._favorite_target_options(target_type_var.get(), rooms, room_names, groups)
            labels = [label for label, _target in options]
            target_lookup.update(dict(options))
            target_combo.configure(values=labels)
            target_var.set(labels[0] if labels else "")

        update_targets()
        target_type_combo.bind("<<ComboboxSelected>>", update_targets)

        actions_frame = ttk.Frame(frame, style="CardBody.TFrame")
        actions_frame.grid(row=2, column=0, sticky="w", pady=(0, 8))
        ttk.Button(
            actions_frame,
            text="Save Favorite",
            style="Primary.TButton",
            command=lambda: self.on_save_favorite(
                favorite_name_var,
                target_type_var,
                target_var,
                action_var,
                target_lookup,
            ),
        ).pack(side="left", padx=(0, 8))
        ttk.Button(
            actions_frame,
            text="Delete Favorite",
            style="Danger.TButton",
            command=lambda: self.on_delete_favorite(favorite_name_var),
        ).pack(side="left")

        ttk.Separator(frame, style="Divider.TSeparator").grid(row=3, column=0, sticky="ew", pady=(8, 8))

        if not favorites:
            ttk.Label(frame, text="No favorites saved yet.", style="CardMuted.TLabel").grid(row=4, column=0, sticky="w")
            return

        device_records = {
            device["ip"]: device
            for devices_in_room in rooms.values()
            for device in devices_in_room
        }
        for row_index, (favorite_name, favorite) in enumerate(sorted(favorites.items()), start=4):
            favorite_row = ttk.Frame(frame, style="CardBody.TFrame")
            favorite_row.grid(row=row_index, column=0, sticky="ew", pady=(2, 0))
            favorite_row.columnconfigure(1, weight=1)
            ttk.Label(favorite_row, text=favorite_name, style="Card.TLabel", width=20).grid(row=0, column=0, sticky="w")
            description = self._describe_favorite(favorite, room_names, groups, device_records)
            ttk.Label(favorite_row, text=description, style="CardMuted.TLabel").grid(row=0, column=1, sticky="w", padx=(8, 0))
            ttk.Button(
                favorite_row,
                text="Link",
                style="Secondary.TButton",
                command=lambda name=favorite_name: self.on_create_favorite_link(name),
            ).grid(row=0, column=2, sticky="e", padx=(8, 0))
            ttk.Button(
                favorite_row,
                text="Load",
                style="Ghost.TButton",
                command=lambda name=favorite_name, favorite_data=copy.deepcopy(favorite): self._load_favorite_selection(
                    favorite_name_var,
                    target_type_var,
                    target_var,
                    action_var,
                    target_lookup,
                    update_targets,
                    name,
                    favorite_data,
                ),
            ).grid(row=0, column=3, sticky="e", padx=(6, 0))


    def _render_group_editor(self, rooms, room_names, groups):
        card = tk.Frame(
            self.control_frame,
            bg=SURFACE_COLOR,
            bd=0,
            highlightbackground=BORDER_COLOR,
            highlightcolor=BORDER_COLOR,
            highlightthickness=1,
        )
        card.pack(fill="x", pady=8, padx=4)

        frame = ttk.Frame(card, style="CardContainer.TFrame", padding=12)
        frame.pack(fill="both", expand=True)
        frame.columnconfigure(0, weight=1)

        header = ttk.Frame(frame, style="CardHeader.TFrame")
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(1, weight=1)
        ttk.Label(header, text="Groups", style="CardTitle.TLabel").grid(row=0, column=0, sticky="w")
        summary = f"{len(groups)} saved" if groups else "No saved groups"
        ttk.Label(header, text=summary, style="CardMuted.TLabel").grid(row=0, column=1, sticky="w", padx=(10, 0))
        toggle_text = "Hide Groups" if self._groups_expanded else "Show Groups"
        ttk.Button(
            header,
            text=toggle_text,
            style="Ghost.TButton",
            command=self.toggle_group_editor,
        ).grid(row=0, column=2, sticky="e")

        if not self._groups_expanded:
            return

        name_frame = ttk.Frame(frame, style="CardBody.TFrame")
        name_frame.grid(row=1, column=0, sticky="ew", pady=(10, 8))
        ttk.Label(name_frame, text="Name", style="CardMuted.TLabel").pack(side="left")
        group_name_var = tk.StringVar(value="Group 1")
        group_name_entry = ttk.Entry(name_frame, textvariable=group_name_var, width=28, style="App.TEntry")
        group_name_entry.pack(side="left", padx=(8, 10))
        group_name_entry.bind("<Return>", self._clear_focus_on_return)

        room_vars = {}
        device_vars = {}

        selector_frame = ttk.Frame(frame, style="CardBody.TFrame")
        selector_frame.grid(row=2, column=0, sticky="ew")
        selector_frame.columnconfigure(0, weight=1)
        selector_frame.columnconfigure(1, weight=1)

        rooms_frame = ttk.Frame(selector_frame, style="CardBody.TFrame")
        rooms_frame.grid(row=0, column=0, sticky="nw", padx=(0, 20))
        ttk.Label(rooms_frame, text="Rooms", style="CardMuted.TLabel").pack(anchor="w")

        for room_id, devices_in_room in rooms.items():
            room_label = f"{room_names.get(room_id, f'Room {room_id}')} ({len(devices_in_room)})"
            var = tk.BooleanVar(value=False)
            room_vars[room_id] = var
            ttk.Checkbutton(rooms_frame, text=room_label, variable=var).pack(anchor="w", pady=(4, 0))

        devices_frame = ttk.Frame(selector_frame, style="CardBody.TFrame")
        devices_frame.grid(row=0, column=1, sticky="nw")
        ttk.Label(devices_frame, text="Devices", style="CardMuted.TLabel").pack(anchor="w")

        for devices_in_room in rooms.values():
            for device in devices_in_room:
                ip = device["ip"]
                var = tk.BooleanVar(value=False)
                device_vars[ip] = var
                label = f"{device.get('moduleName', f'Device {ip}')} ({ip})"
                ttk.Checkbutton(devices_frame, text=label, variable=var).pack(anchor="w", pady=(4, 0))

        actions_frame = ttk.Frame(frame, style="CardBody.TFrame")
        actions_frame.grid(row=3, column=0, sticky="w", pady=(10, 8))
        ttk.Button(
            actions_frame,
            text="Save Group",
            style="Primary.TButton",
            command=lambda: self.on_save_group(group_name_var, room_vars, device_vars),
        ).pack(side="left", padx=(0, 8))
        ttk.Button(
            actions_frame,
            text="Delete Group",
            style="Danger.TButton",
            command=lambda: self.on_delete_group(group_name_var),
        ).pack(side="left")

        ttk.Separator(frame, style="Divider.TSeparator").grid(row=4, column=0, sticky="ew", pady=(8, 8))

        if not groups:
            ttk.Label(frame, text="No groups saved yet.", style="CardMuted.TLabel").grid(row=5, column=0, sticky="w")
            return

        device_records = {
            device["ip"]: device
            for devices_in_room in rooms.values()
            for device in devices_in_room
        }
        for row_index, (group_name, group) in enumerate(sorted(groups.items()), start=5):
            group_row = ttk.Frame(frame, style="CardBody.TFrame")
            group_row.grid(row=row_index, column=0, sticky="ew", pady=(2, 0))
            group_row.columnconfigure(1, weight=1)
            ttk.Label(group_row, text=group_name, style="Card.TLabel", width=20).grid(row=0, column=0, sticky="w")
            description = describe_group(group, room_names=room_names, devices=device_records)
            ttk.Label(group_row, text=description, style="CardMuted.TLabel").grid(row=0, column=1, sticky="w", padx=(8, 0))
            ttk.Button(
                group_row,
                text="On",
                style="Primary.TButton",
                command=lambda name=group_name, group_data=copy.deepcopy(group): self.on_toggle_group(
                    name,
                    group_data,
                    True,
                ),
            ).grid(row=0, column=2, sticky="e", padx=(8, 0))
            ttk.Button(
                group_row,
                text="Off",
                style="Secondary.TButton",
                command=lambda name=group_name, group_data=copy.deepcopy(group): self.on_toggle_group(
                    name,
                    group_data,
                    False,
                ),
            ).grid(row=0, column=3, sticky="e", padx=(6, 0))
            ttk.Button(
                group_row,
                text="Toggle",
                style="Ghost.TButton",
                command=lambda name=group_name, group_data=copy.deepcopy(group): self.on_toggle_group_state(
                    name,
                    group_data,
                ),
            ).grid(row=0, column=4, sticky="e", padx=(6, 0))
            ttk.Button(
                group_row,
                text="Link",
                style="Secondary.TButton",
                command=lambda name=group_name: self.on_create_group_toggle_link(name),
            ).grid(row=0, column=5, sticky="e", padx=(6, 0))
            ttk.Button(
                group_row,
                text="Load",
                style="Ghost.TButton",
                command=lambda name=group_name, group_data=copy.deepcopy(group): self._load_group_selection(
                    group_name_var,
                    room_vars,
                    device_vars,
                    name,
                    group_data,
                ),
            ).grid(row=0, column=6, sticky="e", padx=(6, 0))

    def _load_group_selection(self, group_name_var, room_vars, device_vars, group_name, group):
        group_name_var.set(group_name)
        selected_rooms = set(group.get("rooms", []))
        selected_devices = set(group.get("devices", []))

        for room_id, var in room_vars.items():
            var.set(room_id in selected_rooms)
        for ip, var in device_vars.items():
            var.set(ip in selected_devices)

    def _load_favorite_selection(
        self,
        favorite_name_var,
        target_type_var,
        target_var,
        action_var,
        target_lookup,
        update_targets,
        favorite_name,
        favorite,
    ):
        favorite_name_var.set(favorite_name)
        target_type_var.set(favorite.get("target_type", "group"))
        update_targets()
        target = str(favorite.get("target", ""))
        for label, option_target in target_lookup.items():
            if str(option_target) == target:
                target_var.set(label)
                break
        if favorite.get("action") == "toggle":
            action_var.set("Toggle")
        else:
            action_var.set("On" if favorite.get("state") else "Off")

    def toggle_favorites_editor(self):
        self._favorites_expanded = not self._favorites_expanded
        self.schedule_refresh()

    def toggle_group_editor(self):
        self._groups_expanded = not self._groups_expanded
        self.schedule_refresh()

    def on_apply_brightness(self, ip, brightness_var):
        try:
            brightness = max(BRIGHTNESS_MIN, min(BRIGHTNESS_MAX, int(float(brightness_var.get()))))
        except (TypeError, ValueError):
            brightness = DEFAULT_DIMMING

        def apply():
            try:
                response = self.discovery.set_pilot(ip, dimming=brightness, state=True)
                if response:
                    with self._state_lock:
                        self.device_status_cache[ip] = True
                        self.active_ips.add(ip)
                    self._store_device_preferences(ip, dimming=brightness)
                    self.log(f"Brightness for {ip} set to {brightness}%.")
                    self.schedule_status_refresh()
                else:
                    self.log(f"Could not set brightness for {ip}.")
            except Exception as exc:
                self.log(f"Error setting brightness for {ip}: {exc}")

        self._start_worker(apply, "apply-brightness")

    def on_apply_white(self, ip, brightness_var, temperature_var):
        try:
            brightness = int(float(brightness_var.get()))
        except (TypeError, ValueError):
            brightness = DEFAULT_DIMMING
        brightness = max(BRIGHTNESS_MIN, min(BRIGHTNESS_MAX, brightness))

        try:
            temperature = int(float(temperature_var.get()))
        except (TypeError, ValueError):
            temperature = DEFAULT_TEMPERATURE
        temperature = max(TEMPERATURE_MIN, min(TEMPERATURE_MAX, temperature))

        def apply():
            try:
                response = self.discovery.set_color_temperature(ip, temperature, dimming=brightness, turn_on=True)
                if response:
                    self.log(f"Applied white settings to {ip} (brightness {brightness}%, {temperature}K).")
                    with self._state_lock:
                        self.device_status_cache[ip] = True
                        self.active_ips.add(ip)
                    self._store_device_preferences(ip, dimming=brightness, temperature=temperature)
                    self.schedule_status_refresh()
                else:
                    self.log(f"Could not apply white settings to {ip}.")
            except Exception as exc:
                self.log(f"Error applying white settings to {ip}: {exc}")

        self._start_worker(apply, "apply-white")

    def on_apply_color(self, ip, brightness_var, red_var, green_var, blue_var):
        try:
            brightness = int(float(brightness_var.get()))
        except (TypeError, ValueError):
            brightness = DEFAULT_DIMMING
        brightness = max(BRIGHTNESS_MIN, min(BRIGHTNESS_MAX, brightness))

        def to_channel(var):
            try:
                return max(0, min(255, int(float(var.get()))))
            except (TypeError, ValueError):
                return 0

        red = to_channel(red_var)
        green = to_channel(green_var)
        blue = to_channel(blue_var)

        def apply():
            try:
                response = self.discovery.set_color(
                    ip,
                    r=red,
                    g=green,
                    b=blue,
                    dimming=brightness,
                    turn_on=True,
                )
                if response:
                    self.log(f"Applied color to {ip} (R{red} G{green} B{blue}, brightness {brightness}%).")
                    with self._state_lock:
                        self.device_status_cache[ip] = True
                        self.active_ips.add(ip)
                    self._store_device_preferences(ip, dimming=brightness, r=red, g=green, b=blue)
                    self.schedule_status_refresh()
                else:
                    self.log(f"Could not apply color to {ip}.")
            except Exception as exc:
                self.log(f"Error applying color to {ip}: {exc}")

        self._start_worker(apply, "apply-color")

    def on_apply_preset(
        self,
        ip,
        preset,
        brightness_var,
        temperature_var,
        red_var,
        green_var,
        blue_var,
        brightness_label,
        temperature_label,
        red_label,
        green_label,
        blue_label,
    ):
        dimming = preset.get("dimming")
        if dimming is not None:
            brightness_var.set(dimming)
            self._update_scale_label(brightness_label, dimming, "%")

        if "temperature" in preset:
            temperature = preset["temperature"]
            temperature_var.set(temperature)
            self._update_scale_label(temperature_label, temperature, "K")
            self.on_apply_white(ip, brightness_var, temperature_var)
            return

        red = preset.get("r", 0)
        green = preset.get("g", 0)
        blue = preset.get("b", 0)

        red_var.set(red)
        green_var.set(green)
        blue_var.set(blue)

        self._update_scale_label(red_label, red)
        self._update_scale_label(green_label, green)
        self._update_scale_label(blue_label, blue)

        self.on_apply_color(ip, brightness_var, red_var, green_var, blue_var)

    def on_apply_room_scene(self, room_id, device_ips, scene_var, speed_var):
        scene_id = self._parse_scene_selection(scene_var.get())
        if scene_id is None:
            messagebox.showwarning("Scene Required", "Select a scene before applying.")
            return

        try:
            speed_value = int(float(speed_var.get()))
        except (TypeError, ValueError):
            speed_value = None

        if speed_value is not None:
            speed_value = max(20, min(200, speed_value))

        def apply():
            success = False
            for ip in device_ips:
                try:
                    response = self.discovery.set_scene(ip, scene_id=scene_id, speed=speed_value, turn_on=True)
                    if response:
                        success = True
                        with self._state_lock:
                            self.device_status_cache[ip] = True
                            self.active_ips.add(ip)
                    else:
                        self.log(f"Device {ip} did not accept scene {scene_id}.")
                except Exception as exc:
                    self.log(f"Error applying scene {scene_id} to {ip}: {exc}")

            if success:
                with self._state_lock:
                    settings = self._get_room_settings(room_id)
                    settings["sceneId"] = scene_id
                    if speed_value is not None:
                        settings["sceneSpeed"] = speed_value
                self._save_data()
                scene_name = SCENE_MAP.get(scene_id, "Scene")
                self.log(f"Applied scene {scene_id} ({scene_name}) to room {room_id}.")
                self.schedule_status_refresh()
            else:
                self.log(f"Failed to apply scene {scene_id} to room {room_id}.")

        self._start_worker(apply, "apply-room-scene")

    def update_status_periodically(self):
        stop_event = threading.Event()

        def update():
            while not stop_event.is_set():
                state_changed = False
                with self._state_lock:
                    device_ips = list(self.data["devices"].keys())

                for ip in device_ips:
                    if stop_event.is_set():
                        break
                    try:
                        state = self.discovery.get_device_state(ip)
                        with self._state_lock:
                            previous_state = self.device_status_cache.get(ip)

                        if state is None:
                            with self._state_lock:
                                was_online = ip in self.active_ips
                                self.active_ips.discard(ip)
                                if previous_state is not None:
                                    self.device_status_cache[ip] = None
                            if was_online:
                                self.log(f"Device {ip} became unreachable.")
                                state_changed = True
                            if previous_state is not None:
                                state_changed = True
                        else:
                            with self._state_lock:
                                if ip not in self.active_ips:
                                    self.active_ips.add(ip)
                                    state_changed = True
                                if previous_state != state:
                                    self.device_status_cache[ip] = state
                                else:
                                    self.device_status_cache[ip] = state
                            if previous_state != state:
                                self.log(f"Updated status for {ip}: {'On' if state else 'Off'}")
                                state_changed = True
                    except Exception as e:
                        self.log(f"Error while updating status for {ip}: {e}")

                if state_changed:
                    self.schedule_status_refresh()

                if stop_event.wait(5):
                    break

        self._start_worker(update, "status-poller")
        return stop_event

    def on_save_state_shortcut(self, name_var, target_type, target, state):
        try:
            shortcut_name = self._save_state_shortcut_record(name_var, target_type, target, state)
        except ValueError as exc:
            messagebox.showwarning("Invalid Shortcut", str(exc))
            return

        command = f'py wiz_cli.py shortcut "{shortcut_name}"'
        self.log(f"Shortcut '{shortcut_name}' saved. Use: {command}")
        self.focus_set()

    def _save_state_shortcut_record(self, name_var, target_type, target, state):
        shortcut_name = (name_var.get() or "").strip()
        if not shortcut_name:
            raise ValueError("Please enter a shortcut name.")

        state_label = "On" if state else "Off"
        if not shortcut_name.casefold().endswith((" on", " off")):
            shortcut_name = f"{shortcut_name} {state_label}"

        shortcut = {
            "label": shortcut_name,
            "target_type": target_type,
            "target": str(target),
            "action": "state",
            "state": bool(state),
        }

        with self._state_lock:
            self.data.setdefault("shortcuts", {})[shortcut_name] = shortcut

        if not self._save_data():
            raise ValueError("Could not save shortcut.")
        return shortcut_name

    def _choose_link_output_dir(self):
        output_dir = filedialog.askdirectory(title="Choose where to save the shortcut link")
        if not output_dir:
            return None
        return output_dir

    def _create_link(self, link_name, command):
        output_dir = self._choose_link_output_dir()
        if not output_dir:
            return None

        try:
            plan = build_cli_shortcut_plan(link_name, command, output_dir)
            create_windows_shortcut(plan)
        except (RuntimeError, OSError, ValueError) as exc:
            messagebox.showerror("Link Error", f"Could not create link: {exc}")
            return None

        self.log(f"Windows link created for '{link_name}': {plan['path']}")
        messagebox.showinfo("Link Created", f"Created link:\n{plan['path']}")
        self.focus_set()
        return plan

    def on_create_toggle_link(self, name_var, target_type, target):
        link_name = (name_var.get() or "").strip()
        if not link_name:
            messagebox.showwarning("Invalid Shortcut", "Please enter a shortcut name.")
            return

        if not link_name.casefold().endswith(" toggle"):
            link_name = f"{link_name} Toggle"

        self._create_link(link_name, ["toggle", target_type, str(target)])

    def on_create_group_toggle_link(self, group_name):
        self._create_link(f"{group_name} Toggle", ["toggle", "group", group_name])

    def on_create_favorite_link(self, favorite_name):
        self._create_link(favorite_name, ["favorite", favorite_name])

    def on_save_favorite(self, name_var, target_type_var, target_var, action_var, target_lookup):
        favorite_name = (name_var.get() or "").strip()
        target_label = target_var.get()
        target = target_lookup.get(target_label)
        action_label = (action_var.get() or "Toggle").strip().casefold()

        if not target:
            messagebox.showwarning("Invalid Favorite", "Please select a favorite target.")
            return

        try:
            if action_label == "toggle":
                favorite = build_favorite_record(
                    favorite_name,
                    target_type_var.get(),
                    target,
                    action="toggle",
                )
            else:
                favorite = build_favorite_record(
                    favorite_name,
                    target_type_var.get(),
                    target,
                    action_label == "on",
                )
        except ValueError as exc:
            messagebox.showwarning("Invalid Favorite", str(exc))
            return

        with self._state_lock:
            self.data.setdefault("favorites", {})[favorite["label"]] = favorite

        self._save_data()
        self.log(f"Favorite '{favorite['label']}' saved.")
        self.focus_set()
        self.schedule_refresh()

    def on_delete_favorite(self, name_var):
        favorite_name = (name_var.get() or "").strip()
        if not favorite_name:
            messagebox.showwarning("Invalid Favorite", "Please enter a favorite name.")
            return

        with self._state_lock:
            favorites = self.data.setdefault("favorites", {})
            if favorite_name not in favorites:
                messagebox.showwarning("Favorite Not Found", f"Favorite '{favorite_name}' does not exist.")
                return
            del favorites[favorite_name]

        self._save_data()
        self.log(f"Favorite '{favorite_name}' deleted.")
        self.focus_set()
        self.schedule_refresh()

    def on_save_group(self, name_var, room_vars, device_vars):
        group_name = (name_var.get() or "").strip()
        selected_rooms = [
            room_id
            for room_id, var in room_vars.items()
            if var.get()
        ]
        selected_devices = [
            ip
            for ip, var in device_vars.items()
            if var.get()
        ]

        try:
            group = build_group_record(group_name, selected_rooms, selected_devices)
        except ValueError as exc:
            messagebox.showwarning("Invalid Group", str(exc))
            return

        with self._state_lock:
            self.data.setdefault("groups", {})[group_name] = group

        self._save_data()
        self.log(f"Group '{group_name}' saved.")
        self.focus_set()
        self.schedule_refresh()

    def on_delete_group(self, name_var):
        group_name = (name_var.get() or "").strip()
        if not group_name:
            messagebox.showwarning("Invalid Group", "Please enter a group name.")
            return

        with self._state_lock:
            groups = self.data.setdefault("groups", {})
            if group_name not in groups:
                messagebox.showwarning("Group Not Found", f"Group '{group_name}' does not exist.")
                return
            del groups[group_name]

        self._save_data()
        self.log(f"Group '{group_name}' deleted.")
        self.focus_set()
        self.schedule_refresh()

    def _save_device_name_on_return(self, event, ip, name_var):
        self.on_save_device_name(ip, name_var)
        return "break"

    def on_save_device_name(self, ip, name_var):
        new_name = (name_var.get() or "").strip()
        if not new_name:
            messagebox.showwarning("Invalid name", "Please enter a device name.")
            return
        with self._state_lock:
            record = self.data.get("devices", {}).get(ip)
            if not isinstance(record, dict):
                messagebox.showwarning("Device missing", "This device is no longer in the saved list.")
                return
            record["moduleName"] = new_name
        if self._save_data():
            self.log(f"Device {ip} renamed to {new_name}.")
            self.focus_set()
            self.schedule_refresh()

    def on_save_room_name(self, room_id, name_var):
        new_name = (name_var.get() or "").strip()
        if not new_name:
            messagebox.showwarning("Invalid Name", "Please enter a valid room name.")
            return

        with self._state_lock:
            self.data["rooms"][room_id] = new_name
            renamed = rename_generic_room_devices(self.data, room_id, new_name)
        self._save_data()
        self.log(f"Room {room_id} renamed to {new_name}.")
        if renamed:
            self.log(f"Renamed {renamed} unnamed light(s) in {new_name}.")
        self.focus_set()
        self.schedule_refresh()

    def open_music_sync_dialog(self):
        if self.music_sync_dialog and self.music_sync_dialog.winfo_exists():
            self.music_sync_dialog.lift()
            self.music_sync_dialog.focus_force()
            return

        self.music_sync_dialog = MusicSyncDialog(self, self.data)

    def on_close(self):
        self._closing = True
        if self.music_sync_dialog and self.music_sync_dialog.winfo_exists():
            try:
                self.music_sync_dialog._on_close()
            except Exception:
                pass
            self.music_sync_dialog = None
        if self._auto_discovery_job is not None:
            try:
                self.after_cancel(self._auto_discovery_job)
            except tk.TclError:
                pass
            self._auto_discovery_job = None
        self.stop_event.set()
        self.destroy()

    def run(self):
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.mainloop()


if __name__ == "__main__":
    app = WizGUI()
    app.run()
