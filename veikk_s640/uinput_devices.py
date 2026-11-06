"""UInput device abstraction for VEIKK S640 tablet and buttons."""

from typing import Optional
import evdev
from evdev import ecodes, AbsInfo, UInput
from .config import TabletConfig
from .protocol import PenReport
from .filter import AdaptiveSmoothingFilter


class VeikkUinputManager:
    """Manages the virtual 'VEIKK S640 Pen' and 'VEIKK S640 Buttons' devices."""

    def __init__(self, config: TabletConfig, enable_tilt: bool = False):
        self.config = config
        self.enable_tilt = enable_tilt

        self.filter = AdaptiveSmoothingFilter(
            enabled=config.smoothing_enable,
            smoothing_factor=config.smoothing_factor,
            deadzone=config.smoothing_deadzone,
            pressure_smoothing=config.pressure_smoothing
        )

        self.pen_dev: Optional[UInput] = None
        self.btn_dev: Optional[UInput] = None

        self._in_proximity = False
        self._last_tip_down = False
        self._last_btn1 = False
        self._last_btn2 = False
        self._last_eraser = False

        # Motion distance scaling anchor state
        self._anchor_x: Optional[float] = None
        self._anchor_y: Optional[float] = None
        self._last_raw_rx: Optional[float] = None
        self._last_raw_ry: Optional[float] = None

    def setup(self):
        """Create both virtual uinput devices."""
        # 1. Pen Device capabilities
        abs_caps = [
            (ecodes.ABS_X, AbsInfo(value=0, min=0, max=self.config.max_x, fuzz=0, flat=0, resolution=self.config.resolution_x)),
            (ecodes.ABS_Y, AbsInfo(value=0, min=0, max=self.config.max_y, fuzz=0, flat=0, resolution=self.config.resolution_y)),
            (ecodes.ABS_PRESSURE, AbsInfo(value=0, min=0, max=self.config.max_pressure, fuzz=0, flat=0, resolution=0)),
        ]
        if self.enable_tilt:
            abs_caps.append((ecodes.ABS_TILT_X, AbsInfo(value=0, min=-60, max=60, fuzz=0, flat=0, resolution=0)))
            abs_caps.append((ecodes.ABS_TILT_Y, AbsInfo(value=0, min=-60, max=60, fuzz=0, flat=0, resolution=0)))

        pen_keys = [
            ecodes.BTN_TOOL_PEN,
            ecodes.BTN_TOUCH,
            ecodes.BTN_STYLUS,
            ecodes.BTN_STYLUS2,
        ]

        pen_cap = {
            ecodes.EV_KEY: pen_keys,
            ecodes.EV_ABS: abs_caps,
        }

        # 2. Buttons Device capabilities (dedicated device for input-remapper)
        btn_cap = {
            ecodes.EV_KEY: [
                ecodes.BTN_0,  # Pen button 1 (lower)
                ecodes.BTN_1,  # Pen button 2 (upper)
                ecodes.BTN_2,  # Pen button 3 / eraser
            ]
        }

        # Create Buttons device first so it is ready before input-remapper inspects/autoloads
        self.btn_dev = UInput(
            events=btn_cap,
            name="VEIKK S640 Buttons",
            vendor=0x2FEB,
            product=0x0001,
            version=1
        )

        # Standard graphics tablets have NO input_props. Setting INPUT_PROP_POINTER
        # causes the kernel to attach mousedev, which converts 5080 LPI absolute
        # coordinates into runaway relative mouse jumps.
        props = []
        if self.config.input_prop == "direct":
            props.append(ecodes.INPUT_PROP_DIRECT)

        # Create Pen device
        self.pen_dev = UInput(
            events=pen_cap,
            name="VEIKK S640 Pen",
            vendor=0x2FEB,
            product=0x0001,
            version=1,
            input_props=props
        )

    def compute_coordinates(self, raw_x: int, raw_y: int, is_hover: bool = False) -> tuple[int, int]:
        """Transform raw coordinates through area crop, rotation, and distance scaling."""
        base_x, base_y = self.config.transform_coordinates(raw_x, raw_y)

        if self.config.lock_motion_scales:
            scale = self.config.hover_scale
        else:
            scale = self.config.hover_scale if is_hover else self.config.contact_scale

        # 1:1 default mapping
        if abs(scale - 1.0) < 0.001:
            rx = base_x / max(1, self.config.max_x)
            ry = base_y / max(1, self.config.max_y)
            self._anchor_x = rx
            self._anchor_y = ry
            self._last_raw_rx = rx
            self._last_raw_ry = ry
            return base_x, base_y

        rx = max(0.0, min(1.0, base_x / max(1, self.config.max_x)))
        ry = max(0.0, min(1.0, base_y / max(1, self.config.max_y)))

        if self._last_raw_rx is None or self._anchor_x is None:
            self._anchor_x = rx
            self._anchor_y = ry
            self._last_raw_rx = rx
            self._last_raw_ry = ry
            return base_x, base_y

        dx = rx - self._last_raw_rx
        dy = ry - self._last_raw_ry
        self._last_raw_rx = rx
        self._last_raw_ry = ry

        target_rx = self._anchor_x + dx * scale
        target_ry = self._anchor_y + dy * scale

        out_rx = max(0.0, min(1.0, target_rx))
        out_ry = max(0.0, min(1.0, target_ry))

        self._anchor_x = out_rx
        self._anchor_y = out_ry

        out_x = int(round(out_rx * self.config.max_x))
        out_y = int(round(out_ry * self.config.max_y))
        return out_x, out_y

    def dispatch(self, report: PenReport):
        """Translate PenReport into uinput events according to config and button_mode."""
        if not self.pen_dev or not self.btn_dev:
            return

        if not report.in_proximity:
            if self._in_proximity:
                # Pen exited sensing proximity
                self._emit_proximity_out()
            return

        # Pen is in proximity
        if not self._in_proximity:
            # Proximity entered
            self.pen_dev.write(ecodes.EV_KEY, ecodes.BTN_TOOL_PEN, 1)
            self._in_proximity = True
            self._anchor_x = None
            self._anchor_y = None
            self._last_raw_rx = None
            self._last_raw_ry = None

        # Apply anti-jitter & adaptive motion smoothing
        smooth_x, smooth_y = self.filter.filter_position(report.x, report.y)
        smooth_p = self.filter.filter_pressure(report.pressure)

        # Process Coordinates & Pressure
        pressure = self.config.apply_pressure_curve(smooth_p)
        is_touch = 1 if (report.tip_down or pressure > 0) else 0
        is_hover = (is_touch == 0)

        x, y = self.compute_coordinates(smooth_x, smooth_y, is_hover=is_hover)

        self.pen_dev.write(ecodes.EV_ABS, ecodes.ABS_X, x)
        self.pen_dev.write(ecodes.EV_ABS, ecodes.ABS_Y, y)
        self.pen_dev.write(ecodes.EV_ABS, ecodes.ABS_PRESSURE, pressure if is_touch else 0)
        self.pen_dev.write(ecodes.EV_KEY, ecodes.BTN_TOUCH, is_touch)

        # Tilt if active
        if self.enable_tilt and report.tilt_x is not None and report.tilt_y is not None:
            self.pen_dev.write(ecodes.EV_ABS, ecodes.ABS_TILT_X, report.tilt_x)
            self.pen_dev.write(ecodes.EV_ABS, ecodes.ABS_TILT_Y, report.tilt_y)

        # Button dispatching based on button_mode
        if self.config.button_mode == "native":
            # Send to pen uinput as standard tablet barrel buttons
            if report.button1 != self._last_btn1:
                self.pen_dev.write(ecodes.EV_KEY, ecodes.BTN_STYLUS, 1 if report.button1 else 0)
                self._last_btn1 = report.button1
            if report.button2 != self._last_btn2:
                self.pen_dev.write(ecodes.EV_KEY, ecodes.BTN_STYLUS2, 1 if report.button2 else 0)
                self._last_btn2 = report.button2
        elif self.config.button_mode == "remapper":
            # Send ONLY to Buttons uinput device, NEVER to Pen device
            btn_changed = False
            if report.button1 != self._last_btn1:
                self.btn_dev.write(ecodes.EV_KEY, ecodes.BTN_0, 1 if report.button1 else 0)
                self._last_btn1 = report.button1
                btn_changed = True
            if report.button2 != self._last_btn2:
                self.btn_dev.write(ecodes.EV_KEY, ecodes.BTN_1, 1 if report.button2 else 0)
                self._last_btn2 = report.button2
                btn_changed = True
            if report.eraser != self._last_eraser:
                self.btn_dev.write(ecodes.EV_KEY, ecodes.BTN_2, 1 if report.eraser else 0)
                self._last_eraser = report.eraser
                btn_changed = True
            if btn_changed:
                self.btn_dev.syn()

        self.pen_dev.syn()

    def _emit_proximity_out(self):
        """Reset all active contacts when pen leaves the tablet surface."""
        if not self.pen_dev:
            return

        self.pen_dev.write(ecodes.EV_KEY, ecodes.BTN_TOUCH, 0)
        self.pen_dev.write(ecodes.EV_ABS, ecodes.ABS_PRESSURE, 0)

        if self.config.button_mode == "native":
            self.pen_dev.write(ecodes.EV_KEY, ecodes.BTN_STYLUS, 0)
            self.pen_dev.write(ecodes.EV_KEY, ecodes.BTN_STYLUS2, 0)
            self._last_btn1 = False
            self._last_btn2 = False
        elif self.config.button_mode == "remapper" and self.btn_dev:
            if self._last_btn1 or self._last_btn2 or self._last_eraser:
                self.btn_dev.write(ecodes.EV_KEY, ecodes.BTN_0, 0)
                self.btn_dev.write(ecodes.EV_KEY, ecodes.BTN_1, 0)
                self.btn_dev.write(ecodes.EV_KEY, ecodes.BTN_2, 0)
                self.btn_dev.syn()
                self._last_btn1 = False
                self._last_btn2 = False
                self._last_eraser = False

        self.pen_dev.write(ecodes.EV_KEY, ecodes.BTN_TOOL_PEN, 0)
        self.pen_dev.syn()
        self._in_proximity = False
        self._anchor_x = None
        self._anchor_y = None
        self._last_raw_rx = None
        self._last_raw_ry = None
        self.filter.reset()

    def update_config(self, config: TabletConfig):
        """Update active configuration parameters dynamically."""
        self.config = config
        self.filter.enabled = config.smoothing_enable
        self.filter.smoothing_factor = config.smoothing_factor
        self.filter.deadzone = config.smoothing_deadzone
        self.filter.pressure_smoothing = config.pressure_smoothing

    def close(self):
        """Cleanly close uinput devices."""
        if self._in_proximity:
            self._emit_proximity_out()
        if self.pen_dev:
            self.pen_dev.close()
            self.pen_dev = None
        if self.btn_dev:
            self.btn_dev.close()
            self.btn_dev = None
