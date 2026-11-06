"""Unit tests for input-remapper in-app integration and payload builder."""

import unittest
from veikk_s640.remapper import (
    BUTTON_ACTIONS,
    action_key_to_index,
    index_to_action_key,
    build_mapping_payload,
)


class TestRemapperIntegration(unittest.TestCase):

    def test_action_key_indexing(self):
        # Right click should be index 0
        idx = action_key_to_index("mouse:btn_right")
        self.assertEqual(idx, 0)
        self.assertEqual(index_to_action_key(idx), "mouse:btn_right")

        # Pan / Scroll should be index 1
        idx_scroll = action_key_to_index("pan_scroll")
        self.assertEqual(idx_scroll, 1)
        self.assertEqual(index_to_action_key(idx_scroll), "pan_scroll")

        # Undo should be index 4
        idx_undo = action_key_to_index("keyboard:Control_L + z")
        self.assertEqual(idx_undo, 4)
        self.assertEqual(index_to_action_key(idx_undo), "keyboard:Control_L + z")

    def test_build_mapping_payload_defaults(self):
        # When button 2 is pan_scroll, it should be excluded from input-remapper
        payload = build_mapping_payload(
            button1_action="mouse:btn_right",
            button2_action="pan_scroll"
        )
        self.assertEqual(len(payload), 1)
        self.assertEqual(payload[0]["input_combination"][0]["code"], 256)
        self.assertEqual(payload[0]["target_uinput"], "mouse")
        self.assertEqual(payload[0]["output_symbol"], "btn_right")

        # When both are remapper keys, both should be present
        payload_both = build_mapping_payload(
            button1_action="mouse:btn_right",
            button2_action="keyboard:Control_L + z"
        )
        self.assertEqual(len(payload_both), 2)
        self.assertEqual(payload_both[1]["input_combination"][0]["code"], 257)
        self.assertEqual(payload_both[1]["target_uinput"], "keyboard")
        self.assertEqual(payload_both[1]["output_symbol"], "Control_L + z")

    def test_build_mapping_payload_custom_and_disabled(self):
        payload = build_mapping_payload(
            button1_action="custom",
            button2_action="disabled",
            custom1="F5"
        )
        self.assertEqual(len(payload), 1)
        self.assertEqual(payload[0]["input_combination"][0]["code"], 256)
        self.assertEqual(payload[0]["target_uinput"], "keyboard")
        self.assertEqual(payload[0]["output_symbol"], "F5")


if __name__ == '__main__':
    unittest.main()
