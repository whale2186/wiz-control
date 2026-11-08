# UI upgrade

This build keeps the existing WiZ UDP protocol, CLI, tray companion, persistence, groups, favorites, room scenes, and shortcut support while replacing the main Tkinter dashboard.

## Added

- Automatic discovery shortly after launch and every 30 seconds
- Auto-discovery toggle and manual Scan now action
- Live overview cards for saved lights, online lights, rooms, and last scan
- Responsive room and light cards
- Live power-state badges and power buttons
- Direct brightness control
- Fast visual HSV color picker with hue strip, HEX input, RGB preview, and swatches
- Per-device color previews, white-temperature controls, and presets
- Inline room/device rename controls
- Confirmation before removing a saved device
- Empty-state guidance and upgraded activity log styling

## Run

```bash
python wiz_gui.py
```

Tkinter is part of most official Python distributions. On Linux, install the platform's Tk package if needed.
