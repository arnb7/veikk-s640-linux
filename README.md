# VEIKK S640 Linux Userspace Driver & Control Center

Clean-room, high-performance open-source Linux userspace driver daemon and Libadwaita / GTK4 configuration center for the **VEIKK S640 Graphic Tablet** (USB VID `0x2feb`, PID `0x0001`).

Featuring native Wayland/X11 tablet tool semantics, speed-adaptive anti-jitter smoothing, configurable hover & motion distance scaling, real-time pressure calibration with an interactive test pad, and seamless in-app stylus button remapping powered by [input-remapper](https://github.com/sezanzeb/input-remapper).

---

## Highlights & Features

- **Pixel-Accurate Sub-Pixel Digitizer Mapping**:
  Full 5080 LPI resolution tracking mapped across single or multi-monitor setups without edge snapping or coordinate drifting.
- **Speed-Adaptive Anti-Jitter Filter**:
  Eliminates digitizer micro-tremors and hand jitter during slow strokes while maintaining instantaneous response during rapid flicks.
- **Hover & Motion Distance Scaling**:
  Configurable slider to scale down cursor displacement while hovering (e.g. `0.50x` - `0.75x`), eliminating exaggerated cursor jumps on high-resolution displays.
- **Real-Time Pressure Dynamics**:
  Full 8192-level pressure curve calibration (Linear or Gamma curves with adjustable softness and contact threshold) and an interactive Cairo test canvas using `Gtk.GestureStylus`.
- **Integrated In-App Stylus Button Control**:
  Remap pen barrel buttons directly inside the app to mouse clicks, keyboard shortcuts, or custom macros without launching external editors. Includes quick 1-click presets for Krita, GIMP, Blender, and desktop navigation.
- **Input Isolation Architecture**:
  Virtual dual-device design (`VEIKK S640 Pen` for drawing tools + `VEIKK S640 Buttons` for shortcuts) guarantees drawing events never get swallowed or throttled by remapping daemons.

---

## 1. Quick Start / Downloadable App

### Option A: Run the Standalone Downloadable App
Download `veikk-config.pyz` directly from this repository and run it:
```bash
# Make executable and launch
chmod +x veikk-config.pyz
./veikk-config.pyz
```

### Option B: Install System Driver & Daemon
To install the full background service (`veikk-s640.service`), udev rules, desktop launchers, and configuration tools:
```bash
git clone https://github.com/arnb7/veikk-s640-linux.git
cd veikk-s640-linux
sudo ./install.sh
```

Once installed:
- Launch **VEIKK Tablet Settings** from your application menu or run `veikk-config`.
- Check daemon logs anytime: `journalctl -u veikk-s640 -f`.

---

## 2. Architecture

```
                  +----------------------------------+
                  |  VEIKK S640 Hardware (2feb:0001) |
                  +-----------------+----------------+
                                    | USB Interface 2 (Interrupt Transfers)
                                    v
                           [ veikk-s640d ]
                            /            \
                           /              \
                          v                v
          +-----------------------+   +--------------------------+
          |    VEIKK S640 Pen     |   |    VEIKK S640 Buttons    |
          |  (evdev Tablet Tool)  |   |    (evdev Button Pad)    |
          +-----------+-----------+   +------------+-------------+
                      |                            |
                      | ABS_X / ABS_Y              | BTN_0 (Lower Button)
                      | ABS_PRESSURE (0..8191)     | BTN_1 (Upper Button)
                      | BTN_TOUCH / BTN_TOOL_PEN   | BTN_2 (Eraser)
                      v                            v
          +-----------------------+   +--------------------------+
          | libinput / OS Desktop |   |      input-remapper      |
          |  (Krita / GIMP / etc) |   |  (Presets, Macros, Hotkeys)
          +-----------------------+   +--------------------------+
```

### Dual-Device Separation
1. **`VEIKK S640 Pen`**: Emits absolute coordinates, proximity (`BTN_TOOL_PEN`), contact (`BTN_TOUCH`), and pressure (`ABS_PRESSURE`). The system compositor and `libinput` treat it as an official digitizer tool.
2. **`VEIKK S640 Buttons`**: Dedicated button device captured by `input-remapper`. The drawing tool path is never grabbed, avoiding input lag and dropped strokes.

---

## 3. Protocol Specifications

| Item | Specification | Status | Proof / Source |
| :--- | :--- | :--- | :--- |
| **USB VID / PID** | `0x2feb : 0x0001` | **Confirmed** | Hardware descriptors & udev |
| **Interface** | Interface 2 (`bInterfaceNumber = 2`) | **Confirmed** | Endpoint discovery |
| **Report ID & Type** | Byte 0 = `0x09`, Byte 1 = `0x41` (Pen) | **Confirmed** | Reverse-engineered parser |
| **Proximity Mask** | `(byte[2] & 0xA0) == 0xA0` | **Confirmed** | Hardware status byte |
| **Tip Contact** | Byte 2 = `0xA1` or bit `0x01` / pressure > 0 | **Confirmed** | Digitizer state |
| **Barrel Button 1** | Byte 2 bit `0x04` (`0xA4` hover / `0xA5` tip) | **Confirmed** | Lower button |
| **Barrel Button 2** | Byte 2 bit `0x02` (`0xA2` hover / `0xA3` tip) | **Confirmed** | Upper button |
| **Coordinate Bounds** | 30480 × 20320 (5080 LPI, 6" × 4" active area) | **Confirmed** | String descriptor `0x14` |
| **Pressure Range** | 0 to 8191 (16-bit little-endian) | **Confirmed** | String descriptor `0x14` |
| **Init Sequence** | Out reports: `09 01 04`, `09 02 02`, `09 03 02` | **Confirmed** | USB initialization handshake |

---

## 4. Configuration & Settings

Configuration is stored in `~/.config/veikk-s640/config.toml` (or system-wide in `/etc/veikk-s640/config.toml`):

```toml
[tablet]
button_mode = "remapper"
orientation = 0
coord_width = 3
max_x = 30480
max_y = 20320
max_pressure = 8191

[smoothing]
enable = true
factor = 0.45
deadzone = 4
pressure_smoothing = 0.30

[motion]
hover_scale = 1.00
contact_scale = 1.00
lock_scales = true

[buttons]
button1_action = "mouse:btn_right"
button2_action = "keyboard:Control_L + z"
button1_custom = ""
button2_custom = ""
autoload = true

[area]
min_x = 0.000
max_x = 1.000
min_y = 0.000
max_y = 1.000

[pressure]
curve = "linear"
gamma = 1.00
threshold = 0
```

---

## 5. Automated Tests

Run the complete regression test suite:
```bash
python3 -m unittest discover -s tests -v
```
All 39 tests verify:
- Packet validation and proximity lifecycle
- Coordinate transformation across rotations (0°, 90°, 180°, 270°) and active area crops
- Speed-adaptive anti-jitter filtering and deadzone thresholding
- Linear and gamma pressure curve transformations
- Hover distance scaling and anchor tracking
- Input-remapper payload generation and button indexing
- Native stylus button mode (`BTN_STYLUS` / `BTN_STYLUS2`) and libinput keyboard capabilities

---

## 6. Rnote Integration

For complete inking integration with Rnote (Rust + GTK4):
- **Libwacom Database**: `libwacom/veikk-s640.tablet` provides GNOME Shell and libinput tablet recognition.
- **Native Stylus Mode**: `button_mode = "native"` delivers barrel buttons directly to Rnote's canvas for seamless tool switching (Eraser/Selector).
- **Inking Suite**: Full support for scribble-to-erase (G1), hold-to-snap shapes (G2/G12), custom pressure curves (G3/G14), and One-Euro stabilization (G4). See `rnote/docs/veikk_s640.md`.

---

## 7. License

GPL-3.0 License. Open-source, clean-room implementation.
