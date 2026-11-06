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
        # Configure button2 as pan_scroll
        cfg = TabletConfig(
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

        # Step 1: Pen enters proximity at (5000, 5000), no button
        r1 = PenReport(in_proximity=True, tip_down=False, button1=False, button2=False, eraser=False, x=5000, y=5000, pressure=0)
        mgr.dispatch(r1)
        self.assertFalse(mgr._scroll_active)

        # Step 2: User presses and holds button 2 (pan_scroll) at (5000, 5000)
        r2 = PenReport(in_proximity=True, tip_down=False, button1=False, button2=True, eraser=False, x=5000, y=5000, pressure=0)
        mgr.dispatch(r2)
        self.assertTrue(mgr._scroll_active)
        self.assertEqual(mgr._scroll_frozen_x, 5000)
        self.assertEqual(mgr._scroll_frozen_y, 5000)

        # Step 3: User moves pen down to Y=5800 while holding button 2
        # Delta Y = +800 units -> step is 300 units -> 2 scroll ticks down (REL_WHEEL = -2)
        r3 = PenReport(in_proximity=True, tip_down=False, button1=False, button2=True, eraser=False, x=5000, y=5800, pressure=0)
        mgr.dispatch(r3)

        # Cursor MUST be locked at 5000, 5000 (not 5800)
        mgr.pen_dev.write.assert_any_call(ecodes.EV_ABS, ecodes.ABS_X, 5000)
        mgr.pen_dev.write.assert_any_call(ecodes.EV_ABS, ecodes.ABS_Y, 5000)

        # mouse_dev MUST have received REL_WHEEL down (-2)
        mgr.mouse_dev.write.assert_any_call(ecodes.EV_REL, ecodes.REL_WHEEL, -2)
        mgr.mouse_dev.syn.assert_called()

        # Step 4: User releases button 2 at (5000, 5800)
        r4 = PenReport(in_proximity=True, tip_down=False, button1=False, button2=False, eraser=False, x=5000, y=5800, pressure=0)
        mgr.dispatch(r4)
        self.assertFalse(mgr._scroll_active)


if __name__ == '__main__':
    unittest.main()
