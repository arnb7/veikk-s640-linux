"""Unit tests for AdaptiveSmoothingFilter."""

import unittest
from veikk_s640.filter import AdaptiveSmoothingFilter


class TestAdaptiveSmoothingFilter(unittest.TestCase):

    def test_disabled_filter_returns_raw(self):
        f = AdaptiveSmoothingFilter(enabled=False)
        self.assertEqual(f.filter_position(100, 200), (100, 200))
        self.assertEqual(f.filter_position(105, 205), (105, 205))
        self.assertEqual(f.filter_pressure(500), 500)

    def test_deadzone_suppression(self):
        # With deadzone = 4, movements within 4 raw units are held steady
        f = AdaptiveSmoothingFilter(enabled=True, smoothing_factor=0.5, deadzone=4)
        pos0 = f.filter_position(1000, 1000)
        self.assertEqual(pos0, (1000, 1000))

        # Fluctuation of 2 units (dist = 2 <= deadzone 4) -> should suppress
        pos1 = f.filter_position(1002, 1000)
        self.assertEqual(pos1, (1000, 1000))

        pos2 = f.filter_position(998, 1001)
        self.assertEqual(pos2, (1000, 1000))

    def test_smooth_transition_on_motion(self):
        # Moving past deadzone should smoothly interpolate
        f = AdaptiveSmoothingFilter(enabled=True, smoothing_factor=0.5, deadzone=2)
        f.filter_position(1000, 1000)
        out_x, out_y = f.filter_position(1050, 1050)
        # Should be between 1000 and 1050 (smoothed)
        self.assertTrue(1000 < out_x < 1050)
        self.assertTrue(1000 < out_y < 1050)

    def test_rapid_flick_reaches_full_responsiveness(self):
        # Fast movement (e.g. 2000 units) has alpha near 1.0 (zero latency)
        f = AdaptiveSmoothingFilter(enabled=True, smoothing_factor=0.3, deadzone=2)
        f.filter_position(1000, 1000)
        out_x, out_y = f.filter_position(5000, 5000)
        # Should follow closely on fast flick (> 90% distance covered)
        self.assertGreater(out_x, 4600)
        self.assertGreater(out_y, 4600)

    def test_pressure_smoothing_and_instant_lift(self):
        f = AdaptiveSmoothingFilter(enabled=True, pressure_smoothing=0.5)
        # Initial stroke
        p1 = f.filter_pressure(1000)
        self.assertEqual(p1, 1000)

        # Gradual stroke
        p2 = f.filter_pressure(2000)
        self.assertTrue(1000 < p2 < 2000)

        # Instant pen lift (0 pressure)
        p_lift = f.filter_pressure(0)
        self.assertEqual(p_lift, 0)

    def test_reset_clears_history(self):
        f = AdaptiveSmoothingFilter(enabled=True, smoothing_factor=0.5)
        f.filter_position(1000, 1000)
        f.reset()
        # After reset, first new packet becomes the immediate anchor
        new_pos = f.filter_position(5000, 5000)
        self.assertEqual(new_pos, (5000, 5000))


if __name__ == '__main__':
    unittest.main()
