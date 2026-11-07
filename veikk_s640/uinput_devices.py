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
        self.mouse_dev: Optional[UInput] = None

        self._in_proximity = False
        self._last_tip_down = False
        self._last_btn1 = False
        self._last_btn2 = False
        self._last_eraser = False
        self._eraser_active = False

        # Pan / Scroll holding state
        self._scroll_active = False
        self._scroll_last_x: Optional[float] = None
        self._scroll_last_y: Optional[float] = None
        self._scroll_hi_res_accum_x = 0.0
        self._scroll_hi_res_accum_y = 0.0
        self._scroll_discrete_accum_x = 0
        self._scroll_discrete_accum_y = 0
        self._scroll_frozen_x: Optional[int] = None
        self._scroll_frozen_y: Optional[int] = None

        # Motion distance scaling anchor state
        self._anchor_x: Optional[float] = None
        self._anchor_y: Optional[float] = None
        self._last_raw_rx: Optional[float] = None
        self._last_raw_ry: Optional[float] = None

    def _create_pen_device(self):
        """Create virtual Pen UInput device with orientation-aware axes bounds."""
        abs_caps = [
            (ecodes.ABS_X, AbsInfo(value=0, min=0, max=self.config.output_max_x, fuzz=0, flat=0, resolution=self.config.output_res_x)),
            (ecodes.ABS_Y, AbsInfo(value=0, min=0, max=self.config.output_max_y, fuzz=0, flat=0, resolution=self.config.output_res_y)),
            (ecodes.ABS_PRESSURE, AbsInfo(value=0, min=0, max=self.config.max_pressure, fuzz=0, flat=0, resolution=0)),
        ]
        if self.enable_tilt:
            abs_caps.append((ecodes.ABS_TILT_X, AbsInfo(value=0, min=-60, max=60, fuzz=0, flat=0, resolution=0)))
            abs_caps.append((ecodes.ABS_TILT_Y, AbsInfo(value=0, min=-60, max=60, fuzz=0, flat=0, resolution=0)))

        pen_keys = [
            ecodes.BTN_TOOL_PEN,
            ecodes.BTN_TOOL_RUBBER,
            ecodes.BTN_TOUCH,
            ecodes.BTN_STYLUS,
            ecodes.BTN_STYLUS2,
        ]

        pen_cap = {
            ecodes.EV_KEY: pen_keys,
            ecodes.EV_ABS: abs_caps,
        }

        props = []
        if self.config.input_prop == "direct":
            props.append(ecodes.INPUT_PROP_DIRECT)
        else:
            props.append(ecodes.INPUT_PROP_POINTER)

        self.pen_dev = UInput(
            events=pen_cap,
            name="VEIKK S640 Pen",
            vendor=0x2FEB,
            product=0x0001,
            version=1,
            input_props=props
        )

    def _create_mouse_device(self):
        """Create virtual Mouse/Pointer UInput device with absolute coordinates and smooth wheel scrolling."""
        mouse_cap = {
            ecodes.EV_ABS: [
                (ecodes.ABS_X, AbsInfo(value=0, min=0, max=self.config.output_max_x, fuzz=0, flat=0, resolution=self.config.output_res_x)),
                (ecodes.ABS_Y, AbsInfo(value=0, min=0, max=self.config.output_max_y, fuzz=0, flat=0, resolution=self.config.output_res_y)),
            ],
            ecodes.EV_REL: [
                ecodes.REL_X,
                ecodes.REL_Y,
                ecodes.REL_WHEEL,
                ecodes.REL_HWHEEL,
                getattr(ecodes, 'REL_WHEEL_HI_RES', 11),
                getattr(ecodes, 'REL_HWHEEL_HI_RES', 12)
            ],
            ecodes.EV_KEY: [
                ecodes.BTN_LEFT,
                ecodes.BTN_RIGHT,
                ecodes.BTN_MIDDLE
            ]
        }
        self.mouse_dev = UInput(
            events=mouse_cap,
            name="VEIKK S640 Mouse",
            vendor=0x2FEB,
            product=0x0001,
            version=1
        )

    def setup(self):
        """Create virtual uinput devices for pen, buttons, and mouse scroll."""
        # 1. Pen Device capabilities
        self._create_pen_device()

        # 2. Buttons Device capabilities (dedicated device for input-remapper & system shortcuts)
        btn_cap = {
            ecodes.EV_KEY: [
                ecodes.BTN_0,  # Pen button 1 (lower) / Pad 1
                ecodes.BTN_1,  # Pen button 2 (upper) / Pad 2
                ecodes.BTN_2,  # Pen button 3 / eraser / Pad 3
                ecodes.KEY_F13,
                ecodes.KEY_F14,
                ecodes.KEY_F15,
                ecodes.KEY_F16,
                ecodes.KEY_F17,
                ecodes.KEY_F18,
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

        # 3. Mouse Device capabilities (hybrid absolute pointer + smooth wheel scrolling)
        self._create_mouse_device()


    def compute_coordinates(self, raw_x: int, raw_y: int, is_hover: bool = False) -> tuple[int, int]:
        """Transform raw coordinates through area crop, rotation, and distance scaling."""
        base_x, base_y = self.config.transform_coordinates(raw_x, raw_y)

        if self.config.lock_motion_scales:
            scale = self.config.hover_scale
        else:
            scale = self.config.hover_scale if is_hover else self.config.contact_scale

        # 1:1 default mapping
        if abs(scale - 1.0) < 0.001 and not self.config.aspect_compensate:
            rx = base_x / max(1, self.config.output_max_x)
            ry = base_y / max(1, self.config.output_max_y)
            self._anchor_x = rx
            self._anchor_y = ry
            self._last_raw_rx = rx
            self._last_raw_ry = ry
            return base_x, base_y

        rx = max(0.0, min(1.0, base_x / max(1, self.config.output_max_x)))
        ry = max(0.0, min(1.0, base_y / max(1, self.config.output_max_y)))

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

        scale_x = scale
        scale_y = scale
        if self.config.aspect_compensate:
            if self.config.is_portrait:
                # In portrait, horizontal travel is 2.667x faster than vertical on 16:9 displays.
                # Equalize speeds by slowing horizontal travel by 1 / 2.667 = 0.375
                scale_x *= 0.375
            else:
                scale_x *= 0.844

        target_rx = self._anchor_x + dx * scale_x
        target_ry = self._anchor_y + dy * scale_y

        out_rx = max(0.0, min(1.0, target_rx))
        out_ry = max(0.0, min(1.0, target_ry))

        self._anchor_x = out_rx
        self._anchor_y = out_ry

        out_x = int(round(out_rx * self.config.output_max_x))
        out_y = int(round(out_ry * self.config.output_max_y))
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

        # Process Coordinates & Pressure
        # Evaluate contact status so smoothing filter knows whether the pen is touching (writing/drawing)
        smooth_p = self.filter.filter_pressure(report.pressure)
        pressure = self.config.apply_pressure_curve(smooth_p)
        is_touch = 1 if (report.tip_down or pressure > 0 or report.pressure > 0) else 0
        is_hover = (is_touch == 0)

        # Apply anti-jitter & adaptive motion smoothing with touch-aware inking precision
        smooth_x, smooth_y = self.filter.filter_position(report.x, report.y, is_touch=bool(is_touch))

        x, y = self.compute_coordinates(smooth_x, smooth_y, is_hover=is_hover)

        # Check if Pan / Scroll is triggered by holding an assigned button
        b1_is_scroll = (self.config.button1_action == "pan_scroll")
        b2_is_scroll = (self.config.button2_action == "pan_scroll")
        scroll_btn_pressed = (b1_is_scroll and report.button1) or (b2_is_scroll and report.button2)

        # Check if Eraser (Hold to Erase) is triggered
        b1_is_eraser = (self.config.button1_action in ("eraser_hold", "stylus_eraser", "eraser"))
        b2_is_eraser = (self.config.button2_action in ("eraser_hold", "stylus_eraser", "eraser"))
        eraser_wanted = (b1_is_eraser and report.button1) or (b2_is_eraser and report.button2)

        # Native Stylus 1/2 passthrough
        b1_is_stylus1 = (self.config.button1_action == "stylus:btn_stylus")
        b2_is_stylus1 = (self.config.button2_action == "stylus:btn_stylus")
        b1_is_stylus2 = (self.config.button1_action == "stylus:btn_stylus2")
        b2_is_stylus2 = (self.config.button2_action == "stylus:btn_stylus2")

        if eraser_wanted != self._eraser_active:
            self._eraser_active = eraser_wanted
            if eraser_wanted:
                # Switch tool to RUBBER and assert BTN_STYLUS for instant app detection (Rnote, Xournal++, Krita)
                self.pen_dev.write(ecodes.EV_KEY, ecodes.BTN_TOOL_PEN, 0)
                self.pen_dev.write(ecodes.EV_KEY, ecodes.BTN_TOOL_RUBBER, 1)
                self.pen_dev.write(ecodes.EV_KEY, ecodes.BTN_STYLUS, 1)
            else:
                self.pen_dev.write(ecodes.EV_KEY, ecodes.BTN_STYLUS, 0)
                self.pen_dev.write(ecodes.EV_KEY, ecodes.BTN_TOOL_RUBBER, 0)
                self.pen_dev.write(ecodes.EV_KEY, ecodes.BTN_TOOL_PEN, 1)

        if self.config.scroll_require_touch:
            scroll_active = scroll_btn_pressed and bool(is_touch)
        else:
            scroll_active = scroll_btn_pressed

        if scroll_active:
            if not self._scroll_active:
                # Entering scroll mode on this frame
                self._scroll_active = True
                self._scroll_last_x = float(smooth_x)
                self._scroll_last_y = float(smooth_y)
                self._scroll_hi_res_accum_x = 0.0
                self._scroll_hi_res_accum_y = 0.0
                self._scroll_discrete_accum_x = 0
                self._scroll_discrete_accum_y = 0
                self._scroll_frozen_x = x
                self._scroll_frozen_y = y

                # Sync mouse cursor position to stylus location on target monitor
                if self.mouse_dev:
                    desk_x, desk_y = self.config.get_desktop_pointer_coordinates(x, y)
                    self.mouse_dev.write(ecodes.EV_ABS, ecodes.ABS_X, desk_x)
                    self.mouse_dev.write(ecodes.EV_ABS, ecodes.ABS_Y, desk_y)
                    self.mouse_dev.syn()
            else:
                last_x = self._scroll_last_x if self._scroll_last_x is not None else float(smooth_x)
                last_y = self._scroll_last_y if self._scroll_last_y is not None else float(smooth_y)
                raw_dx = float(smooth_x) - last_x
                raw_dy = float(smooth_y) - last_y
                self._scroll_last_x = float(smooth_x)
                self._scroll_last_y = float(smooth_y)

                # Rotate raw sensor deltas into physical display deltas based on tablet orientation
                if self.config.orientation == 90:
                    dx = -raw_dy
                    dy = raw_dx
                elif self.config.orientation == 180:
                    dx = -raw_dx
                    dy = -raw_dy
                elif self.config.orientation == 270:
                    dx = raw_dy
                    dy = -raw_dx
                else:  # 0
                    dx = raw_dx
                    dy = raw_dy

                # Continuous High-Resolution Scroll Scale:
                # 300 raw tablet units (~1.5mm movement) = 1 standard wheel detent (120 hi-res units)
                scale = (120.0 / 300.0) * max(0.1, self.config.scroll_sensitivity)

                # 1. Continuous Vertical Smooth Scrolling
                self._scroll_hi_res_accum_y += dy * scale
                if abs(self._scroll_hi_res_accum_y) >= 1.0:
                    hi_val_y = int(self._scroll_hi_res_accum_y)
                    self._scroll_hi_res_accum_y -= float(hi_val_y)
                    # Trackpad parity: moving pen UP (dy < 0) scrolls page DOWN (positive tick)
                    hi_wheel_y = -hi_val_y if self.config.scroll_natural else hi_val_y

                    if self.mouse_dev:
                        # Position pointer under stylus on target display so compositor targets the active window
                        if self._scroll_frozen_x is not None and self._scroll_frozen_y is not None:
                            desk_x, desk_y = self.config.get_desktop_pointer_coordinates(self._scroll_frozen_x, self._scroll_frozen_y)
                            self.mouse_dev.write(ecodes.EV_ABS, ecodes.ABS_X, desk_x)
                            self.mouse_dev.write(ecodes.EV_ABS, ecodes.ABS_Y, desk_y)

                        # Emit high-resolution sub-wheel events for liquid 60/120fps scrolling
                        if hasattr(ecodes, 'REL_WHEEL_HI_RES'):
                            self.mouse_dev.write(ecodes.EV_REL, ecodes.REL_WHEEL_HI_RES, hi_wheel_y)

                        # Accumulate discrete wheel ticks for legacy applications
                        self._scroll_discrete_accum_y += hi_wheel_y
                        if abs(self._scroll_discrete_accum_y) >= 120:
                            disc_ticks = int(self._scroll_discrete_accum_y / 120)
                            self._scroll_discrete_accum_y -= disc_ticks * 120
                            self.mouse_dev.write(ecodes.EV_REL, ecodes.REL_WHEEL, disc_ticks)
                        self.mouse_dev.syn()

                # 2. Continuous Horizontal Smooth Scrolling
                self._scroll_hi_res_accum_x += dx * scale
                if abs(self._scroll_hi_res_accum_x) >= 1.0:
                    hi_val_x = int(self._scroll_hi_res_accum_x)
                    self._scroll_hi_res_accum_x -= float(hi_val_x)
                    # Trackpad parity: moving pen RIGHT (dx > 0) scrolls page LEFT (positive tick)
                    hi_wheel_x = hi_val_x if self.config.scroll_natural else -hi_val_x

                    if self.mouse_dev:
                        if self._scroll_frozen_x is not None and self._scroll_frozen_y is not None:
                            desk_x, desk_y = self.config.get_desktop_pointer_coordinates(self._scroll_frozen_x, self._scroll_frozen_y)
                            self.mouse_dev.write(ecodes.EV_ABS, ecodes.ABS_X, desk_x)
                            self.mouse_dev.write(ecodes.EV_ABS, ecodes.ABS_Y, desk_y)

                        if hasattr(ecodes, 'REL_HWHEEL_HI_RES'):
                            self.mouse_dev.write(ecodes.EV_REL, ecodes.REL_HWHEEL_HI_RES, hi_wheel_x)

                        self._scroll_discrete_accum_x += hi_wheel_x
                        if abs(self._scroll_discrete_accum_x) >= 120:
                            disc_h_ticks = int(self._scroll_discrete_accum_x / 120)
                            self._scroll_discrete_accum_x -= disc_h_ticks * 120
                            self.mouse_dev.write(ecodes.EV_REL, ecodes.REL_HWHEEL, disc_h_ticks)
                        self.mouse_dev.syn()

            # Keep pen cursor locked at initial scroll anchor and suppress accidental touches/draws
            if self._scroll_frozen_x is not None and self._scroll_frozen_y is not None:
                self.pen_dev.write(ecodes.EV_ABS, ecodes.ABS_X, self._scroll_frozen_x)
                self.pen_dev.write(ecodes.EV_ABS, ecodes.ABS_Y, self._scroll_frozen_y)
            self.pen_dev.write(ecodes.EV_ABS, ecodes.ABS_PRESSURE, 0)
            self.pen_dev.write(ecodes.EV_KEY, ecodes.BTN_TOUCH, 0)
            self.pen_dev.syn()
            return

        if self._scroll_active:
            # Scroll button just released!
            self._scroll_active = False
            self._scroll_last_x = None
            self._scroll_last_y = None
            self._scroll_hi_res_accum_x = 0.0
            self._scroll_hi_res_accum_y = 0.0
            self._scroll_discrete_accum_x = 0
            self._scroll_discrete_accum_y = 0
            self._scroll_frozen_x = None
            self._scroll_frozen_y = None
            # Re-anchor distance scaling to avoid jump
            self._anchor_x = None
            self._anchor_y = None
            self._last_raw_rx = None
            self._last_raw_ry = None

        self.pen_dev.write(ecodes.EV_ABS, ecodes.ABS_X, x)
        self.pen_dev.write(ecodes.EV_ABS, ecodes.ABS_Y, y)
        self.pen_dev.write(ecodes.EV_ABS, ecodes.ABS_PRESSURE, pressure if is_touch else 0)
        self.pen_dev.write(ecodes.EV_KEY, ecodes.BTN_TOUCH, is_touch)

        # Tilt if active
        if self.enable_tilt and report.tilt_x is not None and report.tilt_y is not None:
            self.pen_dev.write(ecodes.EV_ABS, ecodes.ABS_TILT_X, report.tilt_x)
            self.pen_dev.write(ecodes.EV_ABS, ecodes.ABS_TILT_Y, report.tilt_y)

        # Button dispatching based on button_mode (skipping internal driver handlers)
        b1_internal = b1_is_scroll or b1_is_eraser or b1_is_stylus1 or b1_is_stylus2
        b2_internal = b2_is_scroll or b2_is_eraser or b2_is_stylus1 or b2_is_stylus2

        eff_b1 = False if b1_internal else report.button1
        eff_b2 = False if b2_internal else report.button2

        # Stylus 1/2 passthrough if explicitly selected
        if b1_is_stylus1 or b2_is_stylus1:
            s1_down = (b1_is_stylus1 and report.button1) or (b2_is_stylus1 and report.button2)
            if s1_down != self._last_btn1:
                self.pen_dev.write(ecodes.EV_KEY, ecodes.BTN_STYLUS, 1 if s1_down else 0)
                self._last_btn1 = s1_down

        if b1_is_stylus2 or b2_is_stylus2:
            s2_down = (b1_is_stylus2 and report.button1) or (b2_is_stylus2 and report.button2)
            if s2_down != self._last_btn2:
                self.pen_dev.write(ecodes.EV_KEY, ecodes.BTN_STYLUS2, 1 if s2_down else 0)
                self._last_btn2 = s2_down

        if self.config.button_mode == "native":
            # Send non-internal buttons to pen uinput as standard tablet barrel buttons
            if not (b1_is_stylus1 or b2_is_stylus1) and eff_b1 != self._last_btn1:
                self.pen_dev.write(ecodes.EV_KEY, ecodes.BTN_STYLUS, 1 if eff_b1 else 0)
                self._last_btn1 = eff_b1
            if not (b1_is_stylus2 or b2_is_stylus2) and eff_b2 != self._last_btn2:
                self.pen_dev.write(ecodes.EV_KEY, ecodes.BTN_STYLUS2, 1 if eff_b2 else 0)
                self._last_btn2 = eff_b2
        elif self.config.button_mode == "remapper":
            # Send ONLY non-internal buttons to Buttons uinput device, NEVER to Pen device
            btn_changed = False
            if eff_b1 != self._last_btn1:
                self.btn_dev.write(ecodes.EV_KEY, ecodes.BTN_0, 1 if eff_b1 else 0)
                self._last_btn1 = eff_b1
                btn_changed = True
            if eff_b2 != self._last_btn2:
                self.btn_dev.write(ecodes.EV_KEY, ecodes.BTN_1, 1 if eff_b2 else 0)
                self._last_btn2 = eff_b2
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

        self._scroll_active = False
        self._scroll_last_x = None
        self._scroll_last_y = None
        self._scroll_hi_res_accum_x = 0.0
        self._scroll_hi_res_accum_y = 0.0
        self._scroll_discrete_accum_x = 0
        self._scroll_discrete_accum_y = 0
        self._scroll_frozen_x = None
        self._scroll_frozen_y = None

        if self._eraser_active:
            self.pen_dev.write(ecodes.EV_KEY, ecodes.BTN_STYLUS, 0)
            self.pen_dev.write(ecodes.EV_KEY, ecodes.BTN_TOOL_RUBBER, 0)
            self._eraser_active = False

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

    def reset_state(self):
        """Reset internal tracking state on reload or configuration change."""
        self._scroll_active = False
        self._scroll_last_x = None
        self._scroll_last_y = None
        self._scroll_hi_res_accum_x = 0.0
        self._scroll_hi_res_accum_y = 0.0
        self._scroll_discrete_accum_x = 0
        self._scroll_discrete_accum_y = 0
        self._scroll_frozen_x = None
        self._scroll_frozen_y = None
        self._anchor_x = None
        self._anchor_y = None
        self._last_raw_rx = None
        self._last_raw_ry = None
        self._last_btn1 = False
        self._last_btn2 = False
        self._last_eraser = False
        self._eraser_active = False
        self.filter.reset()

    def update_config(self, config: TabletConfig):
        """Update active configuration parameters dynamically."""
        self.config = config
        self.filter.enabled = config.smoothing_enable
        self.filter.smoothing_factor = config.smoothing_factor
        self.filter.deadzone = config.smoothing_deadzone
        self.filter.pressure_smoothing = config.pressure_smoothing

        if self._in_proximity:
            self._emit_proximity_out()
        self.reset_state()

        if self.pen_dev is None:
            self._create_pen_device()
        if self.mouse_dev is None:
            self._create_mouse_device()

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
        if self.mouse_dev:
            self.mouse_dev.close()
            self.mouse_dev = None
