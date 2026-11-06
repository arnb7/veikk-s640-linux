"""Unit tests for VeikkUinputManager event dispatching."""

import unittest
from unittest.mock import MagicMock
from evdev import ecodes
from veikk_s640.config import TabletConfig
from veikk_s640.protocol import PenReport
from veikk_s640.uinput_devices import VeikkUinputManager


class TestVeikkUinputManager(unittest.TestCase):

    def setUp(self):
        self.config_native = TabletConfig(button_mode="native", max_x=1000, max_y=1000, max_pressure=1000)
        self.config_remapper = TabletConfig(button_mode="remapper", max_x=1000, max_y=1000, max_pressure=1000)

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


if __name__ == '__main__':
    unittest.main()
