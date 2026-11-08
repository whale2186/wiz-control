#!/usr/bin/env python3
"""
WiZ Light Control - Native GTK4-Styled Windows Application
Replicates the exact layout, theme, and responsiveness of wiz-gtk for Windows.
"""

import sys
import os
import json
import socket
import threading
import time
from typing import Dict, List, Optional, Tuple

import customtkinter as ctk
import tkinter as tk
from tkinter import colorchooser

# Network constants
WIZ_PORT = 38899
DEFAULT_TIMEOUT = 1.2

# Color presets identical to wiz-gtk
PRESETS = [
    {"name": "Warm White", "r": 255, "g": 235, "b": 200, "hex": "#ffe7c8"},
    {"name": "Daylight", "r": 255, "g": 255, "b": 255, "hex": "#ffffff"},
    {"name": "Candlelight", "r": 255, "g": 175, "b": 75, "hex": "#ffaf4b"},
    {"name": "Sunset", "r": 255, "g": 87, "b": 34, "hex": "#ff5722"},
    {"name": "Rose", "r": 255, "g": 64, "b": 129, "hex": "#ff4081"},
    {"name": "Ocean", "r": 0, "g": 176, "b": 255, "hex": "#00b0ff"},
    {"name": "Forest", "r": 0, "g": 230, "b": 118, "hex": "#00e676"},
    {"name": "Violet", "r": 124, "g": 77, "b": 255, "hex": "#7c4dff"},
]

SCENES = [
    {"id": 6, "name": "Cozy", "icon": "☕"},
    {"id": 3, "name": "Sunset", "icon": "🌅"},
    {"id": 1, "name": "Ocean", "icon": "🌊"},
    {"id": 5, "name": "Fireplace", "icon": "🔥"},
    {"id": 4, "name": "Party", "icon": "🎉"},
    {"id": 7, "name": "Forest", "icon": "🌲"},
    {"id": 30, "name": "Golden Hour", "icon": "✨"},
    {"id": 31, "name": "Pulse", "icon": "💓"},
]


class BulbNetwork:
    """Thread-safe UDP communicator for WiZ bulbs."""

    def __init__(self, ip: str, port: int = WIZ_PORT):
        self.ip = ip
        self.port = port
        self._lock = threading.Lock()
        self._last_send = 0.0
        self._pending_pilot = None
        self._debounce_timer = None

    def send_udp(self, msg: dict, timeout: float = 1.0) -> Optional[dict]:
        with self._lock:
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                sock.settimeout(timeout)
                payload = json.dumps(msg).encode("utf-8")
                sock.sendto(payload, (self.ip, self.port))
                data, _ = sock.recvfrom(2048)
                sock.close()
                return json.loads(data.decode("utf-8"))
            except Exception:
                return None

    def get_state(self) -> Optional[dict]:
        # Retry once if dropped over wifi
        for _ in range(2):
            resp = self.send_udp({"method": "getPilot", "params": {}}, timeout=1.1)
            if resp and "result" in resp:
                return resp["result"]
            time.sleep(0.06)
        return None

    def set_pilot_immediate(self, params: dict):
        def _send():
            with self._lock:
                try:
                    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                    sock.settimeout(0.5)
                    payload = json.dumps({"method": "setPilot", "params": params}).encode("utf-8")
                    sock.sendto(payload, (self.ip, self.port))
                    sock.close()
                except Exception:
                    pass
        threading.Thread(target=_send, daemon=True).start()

    def set_pilot_debounced(self, params: dict):
        self._pending_pilot = params
        now = time.time()
        elapsed = now - self._last_send

        if elapsed >= 0.065:
            self._last_send = now
            req = self._pending_pilot
            self._pending_pilot = None
            if req:
                self.set_pilot_immediate(req)
            return

        if self._debounce_timer:
            self._debounce_timer.cancel()

        remaining = 0.065 - elapsed
        self._debounce_timer = threading.Timer(remaining, self._flush_debounced)
        self._debounce_timer.daemon = True
        self._debounce_timer.start()

    def _flush_debounced(self):
        req = self._pending_pilot
        self._pending_pilot = None
        self._last_send = time.time()
        if req:
            self.set_pilot_immediate(req)


def discover_bulbs(timeout: float = 1.1, on_found=None) -> List[dict]:
    """Scan local network for WiZ lights via broadcast and ARP."""
    discovered = []
    seen = set()
    lock = threading.Lock()

    req = json.dumps({"method": "getSystemConfig", "params": {}}).encode("utf-8")

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.settimeout(timeout)

    try:
        sock.bind(("", 0))
    except Exception:
        pass

    # Broadcast targets
    targets = ["255.255.255.255"]

    # Probe active ARP entries (Linux /proc/net/arp or Windows arp -a)
    arp_ips = []
    if os.path.exists("/proc/net/arp"):
        try:
            with open("/proc/net/arp") as f:
                for line in f:
                    parts = line.split()
                    if len(parts) >= 4 and parts[2] == "0x2":
                        arp_ips.append(parts[0])
        except Exception:
            pass

    # Send broadcasts
    for t in targets + arp_ips:
        try:
            sock.sendto(req, (t, WIZ_PORT))
        except Exception:
            pass

    # Sweep common subnet IPs in background
    def _sweep():
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            local_ip = s.getsockname()[0]
            s.close()
            prefix = local_ip.rsplit(".", 1)[0]
            for host in range(1, 255):
                ip = f"{prefix}.{host}"
                sock.sendto(req, (ip, WIZ_PORT))
        except Exception:
            pass

    threading.Thread(target=_sweep, daemon=True).start()

    start_t = time.time()
    while time.time() - start_t < timeout:
        try:
            data, addr = sock.recvfrom(2048)
            ip = addr[0]
            with lock:
                if ip in seen:
                    continue
                seen.add(ip)

            resp = json.loads(data.decode("utf-8"))
            res = resp.get("result", {})
            mac = res.get("mac", "")
            mod = res.get("moduleName", "WiZ Smart Light")

            info = {"ip": ip, "mac": mac, "model": mod}
            with lock:
                discovered.append(info)

            if on_found:
                on_found(info)
        except socket.timeout:
            break
        except Exception:
            pass

    sock.close()
    return discovered


class WizGtkApp(ctk.CTk):
    """Modern dark GTK4-styled control interface."""

    def __init__(self):
        super().__init__()

        # Appearance & Dimensions (exact match to wiz-gtk)
        ctk.set_appearance_mode("dark")
        self.title("WiZ Light Control")
        self.geometry("450x700")
        self.minsize(420, 640)
        self.configure(fg_color="#12161f")

        # Set Window Icon
        base_dir = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
        icon_p = os.path.join(base_dir, "assets", "icon.ico")
        if os.path.exists(icon_p):
            try:
                self.iconbitmap(icon_p)
            except Exception:
                pass

        # State
        self.client: Optional[BulbNetwork] = None
        self.discovered_bulbs: List[dict] = []
        self.is_online = False
        self.is_on = False
        self.dimming = 75
        self.r, self.g, self.b = 255, 235, 200
        self.temp_k = 2700
        self.updating_ui = False
        self.scan_in_progress = False

        self._build_ui()

        # Start initial scan
        self.after(80, self.start_scan)

    def _build_ui(self):
        # Header Bar
        header = ctk.CTkFrame(self, fg_color="#181d28", height=60, corner_radius=0, border_width=1, border_color="#262f3f")
        header.pack(fill="x", side="top")

        title_box = ctk.CTkFrame(header, fg_color="transparent")
        title_box.pack(side="left", padx=16, pady=8)

        self.title_lbl = ctk.CTkLabel(title_box, text="WiZ Light Control", font=ctk.CTkFont(family="Segoe UI", size=15, weight="bold"), text_color="#f8fafc")
        self.title_lbl.pack(anchor="w")

        self.status_lbl = ctk.CTkLabel(title_box, text="Scanning network...", font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"), text_color="#38bdf8")
        self.status_lbl.pack(anchor="w")

        self.refresh_btn = ctk.CTkButton(
            header, text="↻", width=36, height=36, corner_radius=18,
            fg_color="#222938", hover_color="#2e384e", text_color="#e2e8f0",
            font=ctk.CTkFont(size=16, weight="bold"), command=self.start_scan
        )
        self.refresh_btn.pack(side="right", padx=16, pady=10)

        # Main Scrollable Body
        self.scroll = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.scroll.pack(fill="both", expand=True, padx=6, pady=6)

        # 0. Discovered Bulb Card
        self._build_target_card()

        # 1. Hero Power Card
        self._build_power_card()

        # 2. Brightness Card
        self._build_brightness_card()

        # 3. Color & Tone Card
        self._build_color_card()

        # 4. Scenes Card
        self._build_scenes_card()

    def _build_target_card(self):
        card = ctk.CTkFrame(self.scroll, fg_color="#1a202c", corner_radius=14, border_width=1, border_color="#262f3f")
        card.pack(fill="x", padx=8, pady=5)

        inner = ctk.CTkFrame(card, fg_color="transparent")
        inner.pack(fill="x", padx=14, pady=12)

        info = ctk.CTkFrame(inner, fg_color="transparent")
        info.pack(side="left", fill="both", expand=True)

        lbl = ctk.CTkLabel(info, text="DISCOVERED BULB", font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"), text_color="#94a3b8")
        lbl.pack(anchor="w")

        self.target_sub_lbl = ctk.CTkLabel(info, text="Scanning LAN...", font=ctk.CTkFont(family="Segoe UI", size=12), text_color="#64748b")
        self.target_sub_lbl.pack(anchor="w")

        self.device_dropdown = ctk.CTkOptionMenu(
            inner, values=["Scanning network..."], width=175, height=32,
            fg_color="#222938", button_color="#2b3548", button_hover_color="#38bdf8",
            dropdown_fg_color="#1a202c", font=ctk.CTkFont(size=12, weight="bold"),
            command=self._on_device_selected
        )
        self.device_dropdown.pack(side="right")

    def _build_power_card(self):
        card = ctk.CTkFrame(self.scroll, fg_color="#1a202c", corner_radius=14, border_width=1, border_color="#262f3f")
        card.pack(fill="x", padx=8, pady=5)

        inner = ctk.CTkFrame(card, fg_color="transparent")
        inner.pack(fill="x", padx=14, pady=12)

        # Bulb Glow Canvas
        self.preview_canvas = tk.Canvas(inner, width=46, height=46, bg="#1a202c", highlightthickness=0)
        self.preview_canvas.pack(side="left", padx=(0, 12))
        self._draw_bulb_preview(False, 255, 235, 200, 75)

        info = ctk.CTkFrame(inner, fg_color="transparent")
        info.pack(side="left", fill="both", expand=True)

        self.power_title = ctk.CTkLabel(info, text="Scanning for lights...", font=ctk.CTkFont(family="Segoe UI", size=16, weight="bold"), text_color="#64748b")
        self.power_title.pack(anchor="w")

        self.power_sub = ctk.CTkLabel(info, text="Probing local network...", font=ctk.CTkFont(family="Segoe UI", size=12), text_color="#64748b")
        self.power_sub.pack(anchor="w")

        self.power_switch = ctk.CTkSwitch(
            inner, text="", width=46, height=24,
            progress_color="#22c55e", fg_color="#334155",
            command=self._on_power_toggle
        )
        self.power_switch.pack(side="right")
        self.power_switch.configure(state="disabled")

    def _draw_bulb_preview(self, on: bool, r: int, g: int, b: int, dim: int):
        self.preview_canvas.delete("all")
        if not on:
            self.preview_canvas.create_oval(3, 3, 43, 43, fill="#242b38", outline="#475569", width=2)
            return

        hex_color = f"#{r:02x}{g:02x}{b:02x}"
        # Outer glow
        glow_color = f"#{min(255, int(r*0.6)):02x}{min(255, int(g*0.6)):02x}{min(255, int(b*0.6)):02x}"
        self.preview_canvas.create_oval(1, 1, 45, 45, fill=glow_color, outline="")
        # Inner core
        self.preview_canvas.create_oval(4, 4, 42, 42, fill=hex_color, outline="#ffffff", width=2)

    def _build_brightness_card(self):
        card = ctk.CTkFrame(self.scroll, fg_color="#1a202c", corner_radius=14, border_width=1, border_color="#262f3f")
        card.pack(fill="x", padx=8, pady=5)

        inner = ctk.CTkFrame(card, fg_color="transparent")
        inner.pack(fill="x", padx=14, pady=12)

        header = ctk.CTkFrame(inner, fg_color="transparent")
        header.pack(fill="x", pady=(0, 6))

        title = ctk.CTkLabel(header, text="BRIGHTNESS", font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"), text_color="#94a3b8")
        title.pack(side="left")

        self.bright_val_lbl = ctk.CTkLabel(header, text="75%", font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"), text_color="#94a3b8")
        self.bright_val_lbl.pack(side="right")

        self.bright_slider = ctk.CTkSlider(
            inner, from_=10, to=100, number_of_steps=90,
            progress_color="#38bdf8", button_color="#f8fafc", button_hover_color="#38bdf8",
            command=self._on_bright_slider
        )
        self.bright_slider.set(self.dimming)
        self.bright_slider.pack(fill="x", pady=6)

        # Quick chips (25%, 50%, 75%, 100%)
        chips = ctk.CTkFrame(inner, fg_color="transparent")
        chips.pack(fill="x", pady=(4, 0))

        for pct in [25, 50, 75, 100]:
            btn = ctk.CTkButton(
                chips, text=f"{pct}%", height=28, corner_radius=8,
                fg_color="#242c3d", hover_color="#2e384e", text_color="#e2e8f0",
                font=ctk.CTkFont(size=12, weight="bold"),
                command=lambda p=pct: self._set_brightness(p)
            )
            btn.pack(side="left", expand=True, fill="x", padx=3)

    def _build_color_card(self):
        card = ctk.CTkFrame(self.scroll, fg_color="#1a202c", corner_radius=14, border_width=1, border_color="#262f3f")
        card.pack(fill="x", padx=8, pady=5)

        inner = ctk.CTkFrame(card, fg_color="transparent")
        inner.pack(fill="x", padx=14, pady=12)

        header = ctk.CTkFrame(inner, fg_color="transparent")
        header.pack(fill="x", pady=(0, 6))

        title = ctk.CTkLabel(header, text="COLOR PRESETS", font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"), text_color="#94a3b8")
        title.pack(side="left")

        custom_btn = ctk.CTkButton(
            header, text="🎨 Picker", width=70, height=24, corner_radius=6,
            fg_color="#222938", hover_color="#2b3548", text_color="#e2e8f0",
            font=ctk.CTkFont(size=11, weight="bold"), command=self._pick_custom_color
        )
        custom_btn.pack(side="right")

        # Presets 2x4 Grid
        row1 = ctk.CTkFrame(inner, fg_color="transparent")
        row1.pack(fill="x", pady=3)
        row2 = ctk.CTkFrame(inner, fg_color="transparent")
        row2.pack(fill="x", pady=3)

        for i, preset in enumerate(PRESETS):
            parent = row1 if i < 4 else row2
            btn = ctk.CTkButton(
                parent, text=f"● {preset['name']}", height=32, corner_radius=8,
                fg_color="#222938", hover_color="#2b3548", text_color=preset["hex"],
                border_width=1, border_color="#334155",
                font=ctk.CTkFont(size=11, weight="bold"),
                command=lambda p=preset: self._set_preset(p)
            )
            btn.pack(side="left", expand=True, fill="x", padx=3)

        # White Temperature
        temp_header = ctk.CTkFrame(inner, fg_color="transparent")
        temp_header.pack(fill="x", pady=(10, 4))

        temp_title = ctk.CTkLabel(temp_header, text="WHITE TEMPERATURE", font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"), text_color="#94a3b8")
        temp_title.pack(side="left")

        self.temp_val_lbl = ctk.CTkLabel(temp_header, text="2700 K", font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"), text_color="#94a3b8")
        self.temp_val_lbl.pack(side="right")

        self.temp_slider = ctk.CTkSlider(
            inner, from_=2200, to=6500, number_of_steps=86,
            progress_color="#ffaf4b", button_color="#f8fafc", button_hover_color="#ffe7c8",
            command=self._on_temp_slider
        )
        self.temp_slider.set(self.temp_k)
        self.temp_slider.pack(fill="x", pady=4)

    def _build_scenes_card(self):
        card = ctk.CTkFrame(self.scroll, fg_color="#1a202c", corner_radius=14, border_width=1, border_color="#262f3f")
        card.pack(fill="x", padx=8, pady=5)

        inner = ctk.CTkFrame(card, fg_color="transparent")
        inner.pack(fill="x", padx=14, pady=12)

        title = ctk.CTkLabel(inner, text="SCENES", font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"), text_color="#94a3b8")
        title.pack(anchor="w", pady=(0, 6))

        row1 = ctk.CTkFrame(inner, fg_color="transparent")
        row1.pack(fill="x", pady=3)
        row2 = ctk.CTkFrame(inner, fg_color="transparent")
        row2.pack(fill="x", pady=3)

        for i, sc in enumerate(SCENES):
            parent = row1 if i < 4 else row2
            btn = ctk.CTkButton(
                parent, text=f"{sc['icon']} {sc['name']}", height=34, corner_radius=8,
                fg_color="#222938", hover_color="#2b3548", text_color="#e2e8f0",
                border_width=1, border_color="#334155",
                font=ctk.CTkFont(size=11, weight="bold"),
                command=lambda s=sc: self._set_scene(s["id"])
            )
            btn.pack(side="left", expand=True, fill="x", padx=3)

    # --- Actions & Network Handling ---

    def start_scan(self):
        if self.scan_in_progress:
            return
        self.scan_in_progress = True
        self.status_lbl.configure(text="Scanning network...", text_color="#38bdf8")
        self.target_sub_lbl.configure(text="Discovering WiZ lights on LAN...")
        self.refresh_btn.configure(state="disabled")

        def _bg_scan():
            first_found = [False]

            def _on_found(b):
                if not first_found[0]:
                    first_found[0] = True
                    self.after(0, lambda: self._connect_first_bulb(b))

            bulbs = discover_bulbs(timeout=1.2, on_found=_on_found)
            self.after(0, lambda: self._finish_scan(bulbs))

        threading.Thread(target=_bg_scan, daemon=True).start()

    def _connect_first_bulb(self, b: dict):
        if not self.client:
            self.client = BulbNetwork(b["ip"])
            self.power_switch.configure(state="normal")
            self.power_sub.configure(text=f"{b['ip']} • {b['mac']}")
            self.target_sub_lbl.configure(text=f"Connected to {b['model']} ({b['ip']})")
            self.status_lbl.configure(text=f"● Online ({b['ip']})", text_color="#22c55e")
            self.sync_state()

    def _finish_scan(self, bulbs: List[dict]):
        self.scan_in_progress = False
        self.refresh_btn.configure(state="normal")
        self.discovered_bulbs = bulbs

        if not bulbs:
            self.status_lbl.configure(text="● No bulbs found", text_color="#ef4444")
            self.power_title.configure(text="No lights found", text_color="#ef4444")
            self.power_sub.configure(text="Click refresh to scan again")
            self.target_sub_lbl.configure(text="0 lights found on network")
            self.device_dropdown.configure(values=["No lights discovered"])
            self.device_dropdown.set("No lights discovered")
            self.power_switch.configure(state="disabled")
            return

        labels = [f"{b['ip']} ({b['model']})" for b in bulbs]
        self.device_dropdown.configure(values=labels)
        self.device_dropdown.set(labels[0])
        self.target_sub_lbl.configure(text=f"{len(bulbs)} WiZ bulb(s) discovered on network")

        if not self.client:
            self._connect_first_bulb(bulbs[0])

    def _on_device_selected(self, val: str):
        ip = val.split()[0]
        bulb = next((b for b in self.discovered_bulbs if b["ip"] == ip), None)
        if bulb:
            self.client = BulbNetwork(bulb["ip"])
            self.power_sub.configure(text=f"{bulb['ip']} • {bulb['mac']}")
            self.target_sub_lbl.configure(text=f"{bulb['model']} ({bulb['ip']})")
            self.sync_state()

    def sync_state(self):
        if not self.client:
            return

        def _bg():
            state = self.client.get_state()
            self.after(0, lambda: self._apply_state(state))

        threading.Thread(target=_bg, daemon=True).start()

    def _apply_state(self, state: Optional[dict]):
        if not state:
            return

        self.updating_ui = True
        self.is_online = True
        self.is_on = state.get("state", False)
        self.dimming = state.get("dimming", 75)
        self.r = state.get("r", 255)
        self.g = state.get("g", 235)
        self.b = state.get("b", 200)
        temp = state.get("temp", 0)
        if temp > 0:
            self.temp_k = temp

        self.status_lbl.configure(text=f"● Online ({self.client.ip})", text_color="#22c55e")

        if self.is_on:
            self.power_title.configure(text="Light is ON", text_color="#f8fafc")
            self.power_switch.select()
        else:
            self.power_title.configure(text="Light is OFF", text_color="#64748b")
            self.power_switch.deselect()

        self.bright_slider.set(self.dimming)
        self.bright_val_lbl.configure(text=f"{self.dimming}%")

        if self.temp_k > 0:
            self.temp_slider.set(self.temp_k)
            self._update_temp_label(self.temp_k)

        self._draw_bulb_preview(self.is_on, self.r, self.g, self.b, self.dimming)
        self.updating_ui = False

    def _on_power_toggle(self):
        if self.updating_ui or not self.client:
            return
        on = bool(self.power_switch.get())
        self.is_on = on
        if on:
            self.power_title.configure(text="Light is ON", text_color="#f8fafc")
            self._draw_bulb_preview(True, self.r, self.g, self.b, self.dimming)
        else:
            self.power_title.configure(text="Light is OFF", text_color="#64748b")
            self._draw_bulb_preview(False, 0, 0, 0, 0)

        self.client.set_pilot_immediate({"state": on})

    def _on_bright_slider(self, val):
        pct = int(val)
        self.bright_val_lbl.configure(text=f"{pct}%")
        if self.updating_ui or not self.client:
            return
        self.dimming = pct
        if self.is_on:
            self._draw_bulb_preview(True, self.r, self.g, self.b, pct)
        self.client.set_pilot_debounced({"state": True, "dimming": pct})

    def _set_brightness(self, pct: int):
        self.bright_slider.set(pct)
        self._on_bright_slider(pct)

    def _on_temp_slider(self, val):
        k = int(val)
        self._update_temp_label(k)
        if self.updating_ui or not self.client:
            return
        self.temp_k = k
        if not self.is_on:
            self.power_switch.select()
            self._on_power_toggle()
        self.client.set_pilot_debounced({"state": True, "temp": k, "dimming": self.dimming})

    def _update_temp_label(self, k: int):
        desc = "Warm"
        if k > 4500:
            desc = "Cool"
        elif k > 3200:
            desc = "Neutral"
        self.temp_val_lbl.configure(text=f"{k} K ({desc})")

    def _set_preset(self, p: dict):
        if not self.client:
            return
        self.r, self.g, self.b = p["r"], p["g"], p["b"]
        if not self.is_on:
            self.power_switch.select()
            self.power_title.configure(text="Light is ON", text_color="#f8fafc")
            self.is_on = True

        self._draw_bulb_preview(True, self.r, self.g, self.b, self.dimming)
        self.client.set_pilot_debounced({"state": True, "r": self.r, "g": self.g, "b": self.b, "dimming": self.dimming})

    def _set_scene(self, scene_id: int):
        if not self.client:
            return
        if not self.is_on:
            self.power_switch.select()
            self.power_title.configure(text="Light is ON", text_color="#f8fafc")
            self.is_on = True
        self.client.set_pilot_immediate({"state": True, "sceneId": scene_id, "speed": 100})

    def _pick_custom_color(self):
        if not self.client:
            return
        color = colorchooser.askcolor(title="Choose Light Color", initialcolor=f"#{self.r:02x}{self.g:02x}{self.b:02x}")
        if color and color[0]:
            r, g, b = [int(c) for c in color[0]]
            self.r, self.g, self.b = r, g, b
            if not self.is_on:
                self.power_switch.select()
                self.power_title.configure(text="Light is ON", text_color="#f8fafc")
                self.is_on = True
            self._draw_bulb_preview(True, r, g, b, self.dimming)
            self.client.set_pilot_debounced({"state": True, "r": r, "g": g, "b": b, "dimming": self.dimming})


if __name__ == "__main__":
    app = WizGtkApp()
    app.mainloop()
