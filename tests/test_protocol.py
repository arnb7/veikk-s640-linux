"""Unit tests for VEIKK S640 protocol parser."""

import unittest
from veikk_s640.protocol import VeikkProtocolParser, PenReport


class TestVeikkProtocolParser(unittest.TestCase):

    def setUp(self):
        self.parser = VeikkProtocolParser(coord_width=2, max_x=32767, max_y=32767, max_pressure=8191)

    def test_invalid_short_packet(self):
        self.assertIsNone(self.parser.parse_packet(bytes([0x09, 0x41])))
        self.assertIsNone(self.parser.parse_packet(b""))

    def test_invalid_report_id(self):
        # Report ID 0x01 instead of 0x09
        raw = bytes([0x01, 0x41, 0xA0, 0x00, 0x10, 0x00, 0x20, 0x00, 0x00])
        self.assertIsNone(self.parser.parse_packet(raw))

    def test_non_pen_report(self):
        # Type 0x42 (keys) instead of 0x41 (pen)
        raw = bytes([0x09, 0x42, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00])
        self.assertIsNone(self.parser.parse_packet(raw))

    def test_pen_hover_report(self):
        # 0x09 0x41 0xA0 (hover)
        # X = 0x0400 (1024), Y = 0x0800 (2048), P = 0
        raw = bytes([
            0x09, 0x41, 0xA0,
            0x00, 0x04,       # X = 1024
            0x00, 0x08,       # Y = 2048
            0x00, 0x00        # Pressure = 0
        ])
        rpt = self.parser.parse_packet(raw)
        self.assertIsNotNone(rpt)
        self.assertTrue(rpt.in_proximity)
        self.assertFalse(rpt.tip_down)
        self.assertFalse(rpt.button1)
        self.assertFalse(rpt.button2)
        self.assertFalse(rpt.eraser)
        self.assertEqual(rpt.x, 1024)
        self.assertEqual(rpt.y, 2048)
        self.assertEqual(rpt.pressure, 0)
        self.assertIsNone(rpt.tilt_x)

    def test_pen_tip_contact(self):
        # 0x09 0x41 0xA1 (tip down)
        # X = 16384 (0x4000), Y = 16384 (0x4000), P = 4096 (0x1000)
        raw = bytes([
            0x09, 0x41, 0xA1,
            0x00, 0x40,
            0x00, 0x40,
            0x00, 0x10
        ])
        rpt = self.parser.parse_packet(raw)
        self.assertIsNotNone(rpt)
        self.assertTrue(rpt.in_proximity)
        self.assertTrue(rpt.tip_down)
        self.assertFalse(rpt.button1)
        self.assertFalse(rpt.button2)
        self.assertEqual(rpt.x, 16384)
        self.assertEqual(rpt.y, 16384)
        self.assertEqual(rpt.pressure, 4096)

    def test_barrel_buttons(self):
        # Button 1 (bit 0x04): status 0xA4 (hover + btn1)
        raw_b1 = bytes([0x09, 0x41, 0xA4, 0x64, 0x00, 0xC8, 0x00, 0x00, 0x00])
        rpt1 = self.parser.parse_packet(raw_b1)
        self.assertIsNotNone(rpt1)
        self.assertTrue(rpt1.button1)
        self.assertFalse(rpt1.button2)
        self.assertFalse(rpt1.tip_down)

        # Button 2 (bit 0x02): status 0xA2 (hover + btn2)
        raw_b2 = bytes([0x09, 0x41, 0xA2, 0x64, 0x00, 0xC8, 0x00, 0x00, 0x00])
        rpt2 = self.parser.parse_packet(raw_b2)
        self.assertIsNotNone(rpt2)
        self.assertFalse(rpt2.button1)
        self.assertTrue(rpt2.button2)
        self.assertFalse(rpt2.tip_down)

        # Eraser / Button 3 (bit 0x08): status 0xA8
        raw_er = bytes([0x09, 0x41, 0xA8, 0x64, 0x00, 0xC8, 0x00, 0x00, 0x00])
        rpte = self.parser.parse_packet(raw_er)
        self.assertIsNotNone(rpte)
        self.assertTrue(rpte.eraser)

    def test_out_of_proximity(self):
        # Out of proximity status 0xC0
        raw = bytes([0x09, 0x41, 0xC0, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00])
        rpt = self.parser.parse_packet(raw)
        self.assertIsNotNone(rpt)
        self.assertFalse(rpt.in_proximity)
        self.assertFalse(rpt.tip_down)
        self.assertFalse(rpt.button1)
        self.assertFalse(rpt.button2)

    def test_tilt_support_when_length_greater_than_12(self):
        # 13 bytes packet with tilt at bytes 11 and 12
        raw = bytearray([
            0x09, 0x41, 0xA1,
            0x00, 0x10,
            0x00, 0x10,
            0x00, 0x05,
            0x00, 0x00,       # bytes 9, 10 padding
            0x1E,             # byte 11: Tilt X = +30
            0xE2              # byte 12: Tilt Y = -30 (0xE2 in two's complement)
        ])
        rpt = self.parser.parse_packet(raw)
        self.assertIsNotNone(rpt)
        self.assertEqual(rpt.tilt_x, 30)
        self.assertEqual(rpt.tilt_y, -30)

    def test_coordinate_width_3(self):
        parser3 = VeikkProtocolParser(coord_width=3)
        # X = 0x010203 (66051), Y = 0x040506 (263430), P = 1000
        raw = bytes([
            0x09, 0x41, 0xA0,
            0x03, 0x02, 0x01, # X = 66051
            0x06, 0x05, 0x04, # Y = 263430
            0xE8, 0x03        # Pressure = 1000
        ])
        rpt = parser3.parse_packet(raw)
        self.assertIsNotNone(rpt)
        self.assertEqual(rpt.x, 66051)
        self.assertEqual(rpt.y, 263430)
    def test_real_hardware_s640_packet(self):
        # Captured from real S640 hardware: raw=09 41 a0 47 0b 00 96 20 00 00 00 00 00
        # Coord width 3: X=0x000B47 (2887), Y=0x002096 (8342), P=0, hover
        parser_hw = VeikkProtocolParser(coord_width=3, max_x=30480, max_y=20320, max_pressure=8191)
        raw = bytes([0x09, 0x41, 0xA0, 0x47, 0x0B, 0x00, 0x96, 0x20, 0x00, 0x00, 0x00, 0x00, 0x00])
        rpt = parser_hw.parse_packet(raw)
        self.assertIsNotNone(rpt)
        self.assertTrue(rpt.in_proximity)
        self.assertFalse(rpt.tip_down)
        self.assertEqual(rpt.x, 2887)
        self.assertEqual(rpt.y, 8342)
        self.assertEqual(rpt.pressure, 0)


if __name__ == '__main__':
    unittest.main()

