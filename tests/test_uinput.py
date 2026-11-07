"""Unit tests for VeikkUinputManager event dispatching."""

import unittest
from unittest.mock import MagicMock
from evdev import ecodes
from veikk_s640.config import TabletConfig
from veikk_s640.protocol import PenReport
from veikk_s640.uinput_devices import VeikkUinputManager


class TestVeikkUinputManager(unittest.TestCase):

    def setUp(self):
        self.config_native = TabletConfig(
            button_mode="native",
            button1_action="mouse:btn_right",
            button2_action="keyboard:Control_L + z",
            max_x=1000,
            max_y=1000,
            max_pressure=1000
        )
        self.config_remapper = TabletConfig(
            button_mode="remapper",
            button1_action="mouse:btn_right",
            button2_action="keyboard:Control_L + z",
            max_x=1000,
            max_y=1000,
            max_pressure=1000
        )

    def test_remapper_mode_dispatches_buttons_only_to_buttons_dev(self):
        mgr = VeikkUinputManager(self.config_remapper)
        mgr.pen_dev = MagicMock()
        mgr.btn_dev = MagicMock()

        # 1. Pen in hover with button 1 pressed
        report1 = PenReport(
            in_proximity=True,
            tip_down=False,
            button1=True,
            button2=False,
            eraser=False,
            x=500,
            y=500,
            pressure=0
        )
        mgr.dispatch(report1)

        # In remapper mode, pen_dev should NOT receive BTN_STYLUS or BTN_STYLUS2
        pen_written_keys = [call.args[1] for call in mgr.pen_dev.write.call_args_list if call.args[0] == ecodes.EV_KEY]
        self.assertNotIn(ecodes.BTN_STYLUS, pen_written_keys)
        self.assertNotIn(ecodes.BTN_STYLUS2, pen_written_keys)

        # btn_dev MUST receive BTN_0 = 1
        mgr.btn_dev.write.assert_any_call(ecodes.EV_KEY, ecodes.BTN_0, 1)
        mgr.btn_dev.syn.assert_called()

        # 2. Release button 1 and press button 2
        report2 = PenReport(
            in_proximity=True,
            tip_down=False,
            button1=False,
            button2=True,
            eraser=False,
            x=500,
            y=500,
            pressure=0
        )
        mgr.btn_dev.reset_mock()
        mgr.dispatch(report2)
        mgr.btn_dev.write.assert_any_call(ecodes.EV_KEY, ecodes.BTN_0, 0)
        mgr.btn_dev.write.assert_any_call(ecodes.EV_KEY, ecodes.BTN_1, 1)

    def test_native_mode_dispatches_buttons_to_pen_dev(self):
        mgr = VeikkUinputManager(self.config_native)
        mgr.pen_dev = MagicMock()
        mgr.btn_dev = MagicMock()

        report = PenReport(
            in_proximity=True,
            tip_down=False,
            button1=True,
            button2=True,
            eraser=False,
            x=500,
            y=500,
            pressure=0
        )
        mgr.dispatch(report)

        # In native mode, pen_dev receives BTN_STYLUS and BTN_STYLUS2
        mgr.pen_dev.write.assert_any_call(ecodes.EV_KEY, ecodes.BTN_STYLUS, 1)
        mgr.pen_dev.write.assert_any_call(ecodes.EV_KEY, ecodes.BTN_STYLUS2, 1)

        # btn_dev must NOT be called
        mgr.btn_dev.write.assert_not_called()

    def test_eraser_hold_activates_rubber_and_stylus_button(self):
        cfg = TabletConfig(button_mode="remapper", button1_action="eraser_hold", button2_action="pan_scroll")
        mgr = VeikkUinputManager(cfg)
        mgr.pen_dev = MagicMock()
        mgr.btn_dev = MagicMock()

        # 1. Hover without button: BTN_TOOL_PEN is 1
        rpt_hover = PenReport(in_proximity=True, tip_down=False, button1=False, button2=False, eraser=False, x=100, y=200, pressure=0)
        mgr.dispatch(rpt_hover)
        mgr.pen_dev.write.assert_any_call(ecodes.EV_KEY, ecodes.BTN_TOOL_PEN, 1)

        # 2. Press Button 1 (eraser_hold): switches to BTN_TOOL_RUBBER and asserts BTN_STYLUS
        rpt_eraser = PenReport(in_proximity=True, tip_down=True, button1=True, button2=False, eraser=False, x=120, y=220, pressure=400)
        mgr.dispatch(rpt_eraser)
        mgr.pen_dev.write.assert_any_call(ecodes.EV_KEY, ecodes.BTN_TOOL_PEN, 0)
        mgr.pen_dev.write.assert_any_call(ecodes.EV_KEY, ecodes.BTN_TOOL_RUBBER, 1)
        mgr.pen_dev.write.assert_any_call(ecodes.EV_KEY, ecodes.BTN_STYLUS, 1)
        # Should NOT be sent to btn_dev (remapper)
        mgr.btn_dev.write.assert_not_called()

        # 3. Release Button 1: reverts to BTN_TOOL_PEN
        rpt_release = PenReport(in_proximity=True, tip_down=True, button1=False, button2=False, eraser=False, x=130, y=230, pressure=400)
        mgr.dispatch(rpt_release)
        mgr.pen_dev.write.assert_any_call(ecodes.EV_KEY, ecodes.BTN_STYLUS, 0)
        mgr.pen_dev.write.assert_any_call(ecodes.EV_KEY, ecodes.BTN_TOOL_RUBBER, 0)
        mgr.pen_dev.write.assert_any_call(ecodes.EV_KEY, ecodes.BTN_TOOL_PEN, 1)

    def test_proximity_lifecycle(self):
        mgr = VeikkUinputManager(self.config_remapper)
        mgr.pen_dev = MagicMock()
        mgr.btn_dev = MagicMock()

        # Enter proximity
        rpt_in = PenReport(in_proximity=True, tip_down=True, button1=False, button2=False, eraser=False, x=100, y=200, pressure=500)
        mgr.dispatch(rpt_in)
        mgr.pen_dev.write.assert_any_call(ecodes.EV_KEY, ecodes.BTN_TOOL_PEN, 1)
        mgr.pen_dev.write.assert_any_call(ecodes.EV_KEY, ecodes.BTN_TOUCH, 1)
        mgr.pen_dev.write.assert_any_call(ecodes.EV_ABS, ecodes.ABS_PRESSURE, 500)

        # Exit proximity
        rpt_out = PenReport(in_proximity=False, tip_down=False, button1=False, button2=False, eraser=False, x=0, y=0, pressure=0)
        mgr.pen_dev.reset_mock()
        mgr.dispatch(rpt_out)
        mgr.pen_dev.write.assert_any_call(ecodes.EV_KEY, ecodes.BTN_TOUCH, 0)
        mgr.pen_dev.write.assert_any_call(ecodes.EV_ABS, ecodes.ABS_PRESSURE, 0)
        mgr.pen_dev.write.assert_any_call(ecodes.EV_KEY, ecodes.BTN_TOOL_PEN, 0)
        mgr.pen_dev.syn.assert_called()

    def test_hover_distance_scaling(self):
        # 1:1 default scaling
        cfg_1 = TabletConfig(hover_scale=1.0, max_x=1000, max_y=1000)
        mgr_1 = VeikkUinputManager(cfg_1)
        x1, y1 = mgr_1.compute_coordinates(500, 500, is_hover=True)
        self.assertEqual((x1, y1), (500, 500))

        # 0.50x hover scaling
        cfg_half = TabletConfig(hover_scale=0.50, max_x=1000, max_y=1000)
        mgr_half = VeikkUinputManager(cfg_half)

        # First entry point anchors at current coordinate
        x0, y0 = mgr_half.compute_coordinates(400, 400, is_hover=True)
        self.assertEqual((x0, y0), (400, 400))

        # Move by +200 on tablet: scaled displacement should be +100
        x1, y1 = mgr_half.compute_coordinates(600, 600, is_hover=True)
        self.assertEqual(x1, 500)
        self.assertEqual(y1, 500)

    def test_pan_scroll_holding_emits_wheel_and_locks_cursor(self):
        # Configure button2 as pan_scroll with scroll_require_touch=True
        cfg = TabletConfig(
            button1_action="mouse:btn_right",
            button2_action="pan_scroll",
            scroll_sensitivity=1.0,
            scroll_natural=False,
            scroll_require_touch=True,
            max_x=30000,
            max_y=20000,
            smoothing_enable=False
        )
        mgr = VeikkUinputManager(cfg)
        mgr.pen_dev = MagicMock()
        mgr.btn_dev = MagicMock()
        mgr.mouse_dev = MagicMock()

        # Step 1: Pen enters proximity at (5000, 5000), no button
        r1 = PenReport(in_proximity=True, tip_down=False, button1=False, button2=False, eraser=False, x=5000, y=5000, pressure=0)
        mgr.dispatch(r1)
        self.assertFalse(mgr._scroll_active)

        # Step 2: User presses and holds button 2 while HOVERING at (5000, 5000)
        # Because scroll_require_touch is True, HOVER should NOT trigger scroll!
        r2_hover = PenReport(in_proximity=True, tip_down=False, button1=False, button2=True, eraser=False, x=5000, y=5000, pressure=0)
        mgr.dispatch(r2_hover)
        self.assertFalse(mgr._scroll_active)
        mgr.mouse_dev.write.assert_not_called()

        # Step 3: User touches pen tip to surface at (5000, 5000) while holding button 2
        r3_touch = PenReport(in_proximity=True, tip_down=True, button1=False, button2=True, eraser=False, x=5000, y=5000, pressure=600)
        mgr.dispatch(r3_touch)
        self.assertTrue(mgr._scroll_active)
        self.assertEqual(mgr._scroll_frozen_x, 5000)
        self.assertEqual(mgr._scroll_frozen_y, 5000)

        # Step 4: User slides pen down to Y=5800 on surface while holding button 2
        # Delta Y = +800 units -> step is 300 units -> 2 scroll ticks (REL_WHEEL = 2)
        r4_slide = PenReport(in_proximity=True, tip_down=True, button1=False, button2=True, eraser=False, x=5000, y=5800, pressure=600)
        mgr.dispatch(r4_slide)

        # Cursor MUST be locked at 5000, 5000 (not 5800) and touch click suppressed
        mgr.pen_dev.write.assert_any_call(ecodes.EV_ABS, ecodes.ABS_X, 5000)
        mgr.pen_dev.write.assert_any_call(ecodes.EV_ABS, ecodes.ABS_Y, 5000)
        mgr.pen_dev.write.assert_any_call(ecodes.EV_KEY, ecodes.BTN_TOUCH, 0)

        # mouse_dev MUST have received REL_WHEEL (2) and REL_WHEEL_HI_RES (320)
        mgr.mouse_dev.write.assert_any_call(ecodes.EV_REL, ecodes.REL_WHEEL, 2)
        if hasattr(ecodes, 'REL_WHEEL_HI_RES'):
            mgr.mouse_dev.write.assert_any_call(ecodes.EV_REL, ecodes.REL_WHEEL_HI_RES, 320)
        mgr.mouse_dev.syn.assert_called()

        # Step 5: User lifts pen up to hover (tip_down=False, pressure=0)
        r5_lift = PenReport(in_proximity=True, tip_down=False, button1=False, button2=True, eraser=False, x=5000, y=5800, pressure=0)
        mgr.dispatch(r5_lift)
        self.assertFalse(mgr._scroll_active)

    def test_pan_scroll_hover_mode_and_mouse_position_sync(self):
        # By default scroll_require_touch is False: hover-scrolling works out of the box
        cfg = TabletConfig(
            screen_output=["NONE", "NONE", "NONE"],
            button1_action="mouse:btn_right",
            button2_action="pan_scroll",
            scroll_sensitivity=1.0,
            scroll_natural=True,
            scroll_require_touch=False,
            max_x=30000,
            max_y=20000,
            smoothing_enable=False
        )
        mgr = VeikkUinputManager(cfg)
        mgr.pen_dev = MagicMock()
        mgr.btn_dev = MagicMock()
        mgr.mouse_dev = MagicMock()

        # Step 1: Pen hovers at (6000, 7000) with button 2 held
        r1 = PenReport(in_proximity=True, tip_down=False, button1=False, button2=True, eraser=False, x=6000, y=7000, pressure=0)
        mgr.dispatch(r1)
        self.assertTrue(mgr._scroll_active)

        # mouse_dev MUST have synced its cursor position
        mgr.mouse_dev.write.assert_any_call(ecodes.EV_ABS, ecodes.ABS_X, 6000)
        mgr.mouse_dev.write.assert_any_call(ecodes.EV_ABS, ecodes.ABS_Y, 7000)

        # Step 2: Hover glide UP (dy = -600)
        r2 = PenReport(in_proximity=True, tip_down=False, button1=False, button2=True, eraser=False, x=6000, y=6400, pressure=0)
        mgr.dispatch(r2)
        # 600 units / 300 = 2 scroll ticks down (REL_WHEEL = 2)
        mgr.mouse_dev.write.assert_any_call(ecodes.EV_REL, ecodes.REL_WHEEL, 2)
        mgr.mouse_dev.syn.assert_called()

    def test_pan_scroll_portrait_orientation_rotates_deltas(self):
        # Configure button2 as pan_scroll in 270 degree portrait orientation
        cfg = TabletConfig(
            orientation=270,
            button1_action="mouse:btn_right",
            button2_action="pan_scroll",
            scroll_sensitivity=1.0,
            scroll_natural=False,
            max_x=30000,
            max_y=20000,
            smoothing_enable=False
        )
        mgr = VeikkUinputManager(cfg)
        mgr.pen_dev = MagicMock()
        mgr.btn_dev = MagicMock()
        mgr.mouse_dev = MagicMock()

        # Step 1: Touch surface at X=5800, Y=5000 with button 2 held
        r1 = PenReport(in_proximity=True, tip_down=True, button1=False, button2=True, eraser=False, x=5800, y=5000, pressure=600)
        mgr.dispatch(r1)
        self.assertTrue(mgr._scroll_active)

        # Step 2: Slide pen DOWN on desk in 270° orientation
        # On physical hardware in 270°, moving DOWN decreases raw X (from 5800 to 5000, raw_dx = -800)
        r2 = PenReport(in_proximity=True, tip_down=True, button1=False, button2=True, eraser=False, x=5000, y=5000, pressure=600)
        mgr.dispatch(r2)

        mgr.mouse_dev.write.assert_any_call(ecodes.EV_REL, ecodes.REL_WHEEL, 2)
        if hasattr(ecodes, 'REL_WHEEL_HI_RES'):
            mgr.mouse_dev.write.assert_any_call(ecodes.EV_REL, ecodes.REL_WHEEL_HI_RES, 320)
        mgr.mouse_dev.syn.assert_called()

    def test_pan_scroll_natural_trackpad_parity(self):
        # Configure button2 as pan_scroll with scroll_natural=True (touchpad style)
        cfg = TabletConfig(
            button1_action="mouse:btn_right",
            button2_action="pan_scroll",
            scroll_sensitivity=1.0,
            scroll_natural=True,
            max_x=30000,
            max_y=20000,
            smoothing_enable=False
        )
        mgr = VeikkUinputManager(cfg)
        mgr.pen_dev = MagicMock()
        mgr.btn_dev = MagicMock()
        mgr.mouse_dev = MagicMock()

        # Step 1: Touch surface at (5000, 5000) with button 2 held
        r1 = PenReport(in_proximity=True, tip_down=True, button1=False, button2=True, eraser=False, x=5000, y=5000, pressure=600)
        mgr.dispatch(r1)
        self.assertTrue(mgr._scroll_active)

        # Step 2: Slide pen UP (dy = -800)
        # On trackpad, moving up scrolls DOWN (REL_WHEEL = 2)
        r2 = PenReport(in_proximity=True, tip_down=True, button1=False, button2=True, eraser=False, x=5000, y=4200, pressure=600)
        mgr.dispatch(r2)
        mgr.mouse_dev.write.assert_any_call(ecodes.EV_REL, ecodes.REL_WHEEL, 2)

        # Step 3: Slide pen LEFT (dx = -800)
        # On trackpad, moving left scrolls RIGHT (positive tick, REL_HWHEEL = 2)
        r3_left = PenReport(in_proximity=True, tip_down=True, button1=False, button2=True, eraser=False, x=4200, y=4200, pressure=600)
        mgr.dispatch(r3_left)
        mgr.mouse_dev.write.assert_any_call(ecodes.EV_REL, ecodes.REL_HWHEEL, 2)

        # Step 4: Slide pen RIGHT (dx = +800)
        # On trackpad, moving right scrolls LEFT (negative tick, REL_HWHEEL = -2)
        r4_right = PenReport(in_proximity=True, tip_down=True, button1=False, button2=True, eraser=False, x=5000, y=4200, pressure=600)
        mgr.dispatch(r4_right)
        mgr.mouse_dev.write.assert_any_call(ecodes.EV_REL, ecodes.REL_HWHEEL, -2)



    def test_aspect_compensate_slows_horizontal_in_portrait(self):
        # Configure portrait mode with aspect_compensate=True
        cfg = TabletConfig(
            orientation=270,
            hover_scale=1.0,
            aspect_compensate=True,
            max_x=30480,
            max_y=20320
        )
        mgr = VeikkUinputManager(cfg)

        # Initial anchor point
        x0, y0 = mgr.compute_coordinates(10000, 10000, is_hover=True)

        # Move 1000 units on hardware Y (which is horizontal axis on desk in 270°)
        x1, y1 = mgr.compute_coordinates(10000, 11000, is_hover=True)

        # Due to 0.375 aspect compensation on 30480 max_x, horizontal change is scaled to 563 units
        dx_out = x1 - x0
        self.assertAlmostEqual(dx_out, 563, delta=2)


if __name__ == '__main__':
    unittest.main()
