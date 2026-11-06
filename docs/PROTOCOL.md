# VEIKK S640 Protocol Specification & Hardware Verification

This document specifies the exact protocol between the Linux host and the VEIKK S640 graphic tablet (USB VID `0x2feb`, PID `0x0001`).

All specifications below are derived from static disassembly of `TabletParser::parsePenData`, `TabletDevice_Linux::getContext`, and `TabletDevice_Linux::changeMode` in `/usr/lib/vktablet/vktablet` (v3.5.10-9).

---

## 1. USB Interface Topology

| Property | Value | Status | Notes |
| :--- | :--- | :--- | :--- |
| **Vendor ID (VID)** | `0x2feb` | [Disassembly Confirmed] | Shared across multiple VEIKK devices. |
| **Product ID (PID)** | `0x0001` | [Disassembly Confirmed] | Shared by S640 and T10. |
| **Interface Count** | 3 interfaces | [Disassembly Confirmed] | Interfaces 0 and 1 are kernel HID; interface 2 is proprietary. |
| **Target Interface** | Interface 2 (`bInterfaceNumber = 2`) | [Disassembly Confirmed] | Driver detaches kernel driver and claims this interface. |
| **Endpoints** | 1 IN (interrupt), 1 OUT (interrupt) | [Disassembly Confirmed] | Discovered dynamically from interface 2 descriptors. |

---

## 2. Connect-Time Device Interrogation (String Descriptors)

The driver issues standard USB control transfers (`bmRequestType = 0x80`, `bRequest = 0x06`, `wIndex = 0x0409`) for specific string descriptor indices:

1. **String Descriptor `0x16`**:
   - Hardware capture: `06 03 00 00 01 01`.
   - Feature flags returned by hardware firmware.

2. **String Descriptor `0x14` (Hardware Boundaries & Coordinate Width)**:
   - Hardware capture: `12 03 10 77 00 60 4f 00 ff 1f d8 13 03 00 00 00 00 00`
   - Decoded parameters:
     - Bytes `0..2` (`10 77 00`): Max X = `0x007710` = **30480** (Confirmed on HW).
     - Bytes `3..5` (`60 4f 00`): Max Y = `0x004f60` = **20320** (Confirmed on HW).
     - Bytes `6..7` (`ff 1f`): Max Pressure = `0x1fff` = **8191** (8192 levels, Confirmed on HW).
     - Bytes `8..9` (`d8 13`): Resolution = `0x13d8` = **5080 LPI** = 200 units/mm (Confirmed on HW).
     - Byte `10` (`03`): **Coordinate width $n = 3$ bytes** (Confirmed on HW).

3. **Product & Firmware Metadata Descriptors**:
   - `Index 0x01`: `VEIKK.INC`
   - `Index 0x02`: `S640`
   - `Index 0x03`: `0000001`
   - `Index 0x17`: `2021/10/12` (Firmware release date).

---

## 3. Host-to-Device Mode Initialization (EP OUT)

Before streaming pen events, the driver sends a sequence of three 3-byte packets to the OUT endpoint:

1. **Mode Packet (`WorkMode = 9`)**:
   `09 01 04`
2. **Stream Enable Packet 1**:
   `09 02 02`
3. **Stream Enable Packet 2**:
   `09 03 02`

---

## 4. Device-to-Host Packet Structure (EP IN)

Packets read from the IN endpoint have length $\ge 9$ bytes (typically 9 or 13 bytes).

```
Offset:  0      1      2          3 ... 3+(n-1)     3+n ... 3+(2n-1)   3+2n ... 4+2n      11       12
Field:  [0x09] [0x41] [STATUS]   [   X (n bytes)  ] [   Y (n bytes)  ] [ PRESSURE (u16) ] [TILT_X] [TILT_Y]
```

### 4.1 Packet Header
- **Byte 0**: Report ID. Must be `0x09`.
- **Byte 1**: Report Type:
  - `0x41`: Stylus / Pen report.
  - `0x42`: Physical bezel buttons (none on S640).
  - `0x43`: Touch wheel / dial (none on S640).

### 4.2 Status Byte (Byte 2)
Disassembly from `TabletParser::parsePenData`:
- `(status & 0xA0) == 0xA0`: Pen in proximity / range.
- **Tip Contact**:
  - `0xA0`: Hover (tip up, no buttons).
  - `0xA1`: Tip down on drawing surface.
- **Buttons and Flags**:
  - Bit 1 (`0x02`): Upper barrel button (`0xA2` hover, `0xA3` tip down).
  - Bit 2 (`0x04`): Lower barrel button (`0xA4` hover, `0xA5` tip down).
  - Bit 3 (`0x08`): Eraser / tail button (`0xA8` hover, `0xA9` tip down).
- **Proximity Loss**:
  - Any status value lacking the `0xA0` mask (e.g. `0xC0`).

### 4.3 Coordinate & Pressure Encoding (Hardware S640 Layout)
- **X Coordinate**: Bytes `3..5` (3 bytes, little-endian). Range: `0 .. 30480`.
- **Y Coordinate**: Bytes `6..8` (3 bytes, little-endian). Range: `0 .. 20320`.
- **Pressure**: Bytes `9..10` (16-bit little-endian integer). Range: `0 .. 8191`.
- **Tilt (Optional)**: If packet length $\ge 13$ bytes, Byte 11 contains Tilt X (-60 to +60 degrees) and Byte 12 contains Tilt Y (-60 to +60 degrees).

---

## 5. Motion Filtering & Configuration Architecture

1. **Adaptive Smoothing Filter (`veikk_s640/filter.py`)**:
   - Digitizers at 5080 LPI produce high-frequency micro-jitter (1 raw unit = 0.005 mm).
   - An adaptive speed-dependent low-pass filter with deadzone suppression eliminates tremor when hovering or drawing slow curves, while dynamically relaxing alpha towards 1.0 on rapid flicks for zero latency.
   - Pressure values are exponentially smoothed during strokes and dropped instantly to 0 upon pen lift.

2. **Libadwaita / GTK4 Configuration Frontend (`veikk_s640/gui.py`, `bin/veikk-config`)**:
   - Replaces the closed-source `vktablet` GUI.
   - Provides live hardware connection badge, service status, interactive drawing test canvas, slider controls for smoothness/deadzone/pressure curves, and desktop launcher integration (`vktablet.desktop`).

