"""Unit tests for VEIKK S640 configuration and coordinate transformation."""

import unittest
from veikk_s640.config import TabletConfig


class TestTabletConfig(unittest.TestCase):

    def test_default_config(self):
        cfg = TabletConfig()
        self.assertEqual(cfg.button_mode, "remapper")
        self.assertEqual(cfg.orientation, 0)
        self.assertEqual(cfg.max_x, 30480)
        self.assertEqual(cfg.max_y, 20320)
        self.assertEqual(cfg.max_pressure, 8191)

    def test_pressure_linear_and_threshold(self):
        cfg = TabletConfig(pressure_threshold=100)
        # Below threshold
        self.assertEqual(cfg.apply_pressure_curve(50), 0)
        self.assertEqual(cfg.apply_pressure_curve(100), 0)
        # Above threshold
        self.assertEqual(cfg.apply_pressure_curve(500), 500)
        # Clamping
        self.assertEqual(cfg.apply_pressure_curve(10000), 8191)

    def test_pressure_gamma(self):
        cfg = TabletConfig(pressure_curve="gamma", pressure_gamma=2.0, max_pressure=8191)
        # Half pressure: 0.5^2 = 0.25 -> 8191 * 0.25 ~ 2047
        val = cfg.apply_pressure_curve(4095)
        self.assertAlmostEqual(val, int(8191 * 0.25), delta=10)

    def test_coordinate_transforms_orientation(self):
        cfg = TabletConfig(max_x=1000, max_y=1000)

        # 0 degrees
        cfg.orientation = 0
        x, y = cfg.transform_coordinates(200, 300)
        self.assertEqual((x, y), (200, 300))

        # 90 degrees clockwise: (x, y) -> (1-y, x)
        cfg.orientation = 90
        x, y = cfg.transform_coordinates(200, 300)
        self.assertEqual((x, y), (700, 200))

        # 180 degrees
        cfg.orientation = 180
        x, y = cfg.transform_coordinates(200, 300)
        self.assertEqual((x, y), (800, 700))

        # 270 degrees
        cfg.orientation = 270
        x, y = cfg.transform_coordinates(200, 300)
        self.assertEqual((x, y), (300, 800))

    def test_active_area_crop(self):
        # Crop to center 50%: min_x=0.25, max_x=0.75, min_y=0.25, max_y=0.75
        cfg = TabletConfig(
            max_x=1000, max_y=1000,
            area_min_x=0.25, area_max_x=0.75,
            area_min_y=0.25, area_max_y=0.75
        )
        # Center of tablet (500, 500) maps to center of screen (500, 500)
        x, y = cfg.transform_coordinates(500, 500)
        self.assertEqual((x, y), (500, 500))

        # Corner of cropped area (250, 250) maps to (0, 0)
        x, y = cfg.transform_coordinates(250, 250)
        self.assertEqual((x, y), (0, 0))

        # Top-right of cropped area (750, 750) maps to (1000, 1000)
        x, y = cfg.transform_coordinates(750, 750)
        self.assertEqual((x, y), (1000, 1000))

    def test_motion_scaling_config(self):
        import tempfile
        import os
        from veikk_s640.config import save_config, load_config

        cfg = TabletConfig(hover_scale=0.60, contact_scale=0.80, lock_motion_scales=False)
        with tempfile.NamedTemporaryFile("w+", delete=False, suffix=".toml") as f:
            tmp_path = f.name

        try:
            save_config(cfg, tmp_path)
            loaded = load_config(tmp_path)
            self.assertAlmostEqual(loaded.hover_scale, 0.60)
            self.assertAlmostEqual(loaded.contact_scale, 0.80)
            self.assertFalse(loaded.lock_motion_scales)
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)


if __name__ == '__main__':
    unittest.main()
