"""Integration with input-remapper for in-app stylus button configuration."""

import os
import json
import logging
import subprocess
from typing import Optional

logger = logging.getLogger("veikk-remapper")

PRESET_DEVICE_NAMES = ["VEIKK S640 Pen", "VEIKK S640 Buttons"]
PRESET_NAME = "default"

# Common friendly button actions: (Display Name, action_key, description)
BUTTON_ACTIONS = [
    ("Right Click (Default)", "mouse:btn_right", "Standard right-click context menu"),
    ("Pan / Scroll (Hold & Move Pen)", "pan_scroll", "Hold pen button & glide up/down to scroll pages/docs"),
    ("Middle Click / Pan", "mouse:btn_middle", "Middle mouse click, canvas pan"),
    ("Left Click", "mouse:btn_left", "Primary mouse button click"),
    ("Undo (Ctrl+Z)", "keyboard:Control_L + z", "Undo previous brush stroke / action"),
    ("Eraser (Hold to Erase — Rnote / Xournal++ / Notes)", "eraser_hold", "Hold button while sliding pen to erase strokes in Rnote, Xournal++, OneNote, Obsidian"),
    ("Redo (Ctrl+Y)", "keyboard:Control_L + y", "Redo action"),
    ("Redo (Ctrl+Shift+Z)", "keyboard:Control_L + Shift_L + z", "Alternate redo shortcut"),
    ("Eraser Tool Toggle (E — Krita, Photoshop)", "keyboard:e", "Toggle eraser tool in Krita, Photoshop, Blender, GIMP"),
    ("Eraser Tool (Xournal++ Delete)", "keyboard:Delete", "Trigger delete / eraser tool in Xournal++"),
    ("Eraser Tool (Rnote Ctrl+4)", "keyboard:Control_L + 4", "Switch tool slot to eraser in Rnote"),
    ("Brush Tool (B)", "keyboard:b", "Switch to brush tool"),
    ("Hand / Pan Canvas (Space)", "keyboard:space", "Pan view while button held down"),
    ("Color Picker (Alt)", "keyboard:Alt_L", "Eyedropper / color sampler in Krita/GIMP"),
    ("Zoom In (Ctrl +)", "keyboard:Control_L + equal", "Zoom in on active canvas"),
    ("Zoom Out (Ctrl -)", "keyboard:Control_L + minus", "Zoom out of active canvas"),
    ("Fit to Screen (Ctrl 0)", "keyboard:Control_L + 0", "Reset zoom to 100%"),
    ("Escape (Cancel)", "keyboard:Escape", "Cancel operation / clear tool"),
    ("Native Stylus Button 1 (BTN_STYLUS)", "stylus:btn_stylus", "Direct hardware BTN_STYLUS barrel event"),
    ("Native Stylus Button 2 (BTN_STYLUS2)", "stylus:btn_stylus2", "Direct hardware BTN_STYLUS2 barrel event"),
    ("Custom Keystroke / Macro", "custom", "Enter any custom keystroke or macro"),
    ("Disabled / Passthrough", "disabled", "Do not remap this button"),
]

WORKFLOW_PRESETS = [
    {
        "name": "Handwriting & Notes (Rnote / Xournal++ / OneNote)",
        "b1": "eraser_hold",
        "b2": "pan_scroll",
        "desc": "Button 1: Hold to Erase | Button 2: Pan & Smooth Page Scroll"
    },
    {
        "name": "Notes (Eraser + Undo)",
        "b1": "eraser_hold",
        "b2": "keyboard:Control_L + z",
        "desc": "Button 1: Hold to Erase | Button 2: Instant Undo (Ctrl+Z)"
    },
    {
        "name": "Web & Document Browsing",
        "b1": "mouse:btn_right",
        "b2": "pan_scroll",
        "desc": "Button 1: Right-Click | Button 2: Pan & Scroll (Hold & Glide Pen)"
    },
    {
        "name": "Digital Painting (Krita / GIMP)",
        "b1": "mouse:btn_right",
        "b2": "keyboard:e",
        "desc": "Button 1: Right-Click (Pop-up Palette) | Button 2: Toggle Eraser (E)"
    },
    {
        "name": "Illustration & Inking",
        "b1": "mouse:btn_right",
        "b2": "keyboard:Control_L + z",
        "desc": "Button 1: Right-Click | Button 2: Instant Undo (Ctrl+Z)"
    },
    {
        "name": "Canvas Navigation",
        "b1": "keyboard:space",
        "b2": "keyboard:Alt_L",
        "desc": "Button 1: Pan Canvas (Space) | Button 2: Eyedropper (Alt)"
    },
    {
        "name": "Desktop Mouse Mode",
        "b1": "mouse:btn_right",
        "b2": "mouse:btn_middle",
        "desc": "Button 1: Right-Click | Button 2: Middle-Click / Auto-scroll"
    },
]


def action_key_to_index(action_key: str) -> int:
    """Find index in BUTTON_ACTIONS for a given action_key."""
    for idx, (_, key, _) in enumerate(BUTTON_ACTIONS):
        if key == action_key:
            return idx
    return len(BUTTON_ACTIONS) - 2  # Custom


def index_to_action_key(idx: int) -> str:
    """Get action_key from BUTTON_ACTIONS index."""
    if 0 <= idx < len(BUTTON_ACTIONS):
        return BUTTON_ACTIONS[idx][1]
    return "custom"


def build_mapping_payload(
    button1_action: str,
    button2_action: str,
    custom1: str = "",
    custom2: str = ""
) -> list[dict]:
    """Build the JSON mappings payload accepted by input-remapper."""
    mappings = []

    def _make_mapping(action: str, custom_val: str, code: int) -> Optional[dict]:
        if action in ("disabled", "pan_scroll", "eraser_hold", "stylus_eraser", "eraser", "stylus:btn_stylus", "stylus:btn_stylus2"):
            return None
        if action == "custom":
            symbol = custom_val.strip()
            if not symbol:
                return None
            target = "mouse" if symbol.lower().startswith("btn_") else "keyboard"
        elif ":" in action:
            target, symbol = action.split(":", 1)
        else:
            target, symbol = "keyboard", action

        return {
            "input_combination": [
                {
                    "type": 1,
                    "code": code
                }
            ],
            "target_uinput": target,
            "output_symbol": symbol,
            "mapping_type": "key_macro"
        }

    m1 = _make_mapping(button1_action, custom1, 256)
    if m1:
        mappings.append(m1)

    m2 = _make_mapping(button2_action, custom2, 257)
    if m2:
        mappings.append(m2)

    return mappings


def apply_remapper_preset(
    button1_action: str,
    button2_action: str,
    custom1: str = "",
    custom2: str = "",
    autoload: bool = True
) -> tuple[bool, str]:
    """Write input-remapper JSON preset and trigger live injection."""
    try:
        mappings = build_mapping_payload(button1_action, button2_action, custom1, custom2)
        base_dir = os.path.expanduser("~/.config/input-remapper-2")

        # 1. Write preset files for all matching device identifiers
        for dev_name in PRESET_DEVICE_NAMES:
            preset_dir = os.path.join(base_dir, "presets", dev_name)
            os.makedirs(preset_dir, exist_ok=True)
            preset_file = os.path.join(preset_dir, f"{PRESET_NAME}.json")
            with open(preset_file, "w", encoding="utf-8") as f:
                json.dump(mappings, f, indent=4)

        # 2. Update autoload in config.json
        cfg_path = os.path.join(base_dir, "config.json")
        cfg_data = {"version": "2.2.1", "autoload": {}}
        if os.path.isfile(cfg_path):
            try:
                with open(cfg_path, "r", encoding="utf-8") as f:
                    cfg_data = json.load(f)
            except Exception:
                pass
        if "autoload" not in cfg_data or not isinstance(cfg_data["autoload"], dict):
            cfg_data["autoload"] = {}

        for dev_name in PRESET_DEVICE_NAMES:
            if autoload:
                cfg_data["autoload"][dev_name] = PRESET_NAME
            else:
                cfg_data["autoload"].pop(dev_name, None)

        os.makedirs(base_dir, exist_ok=True)
        with open(cfg_path, "w", encoding="utf-8") as f:
            json.dump(cfg_data, f, indent=4)

        # 3. Reload daemon / start injection across all devices
        for dev_name in PRESET_DEVICE_NAMES:
            cmd = [
                "input-remapper-control",
                "--command", "start",
                "--device", dev_name,
                "--preset", PRESET_NAME
            ]
            try:
                subprocess.run(cmd, capture_output=True, text=True, timeout=3)
            except Exception:
                pass

        # Trigger daemon autoload command
        try:
            subprocess.run(["input-remapper-control", "--command", "autoload"], capture_output=True, text=True, timeout=3)
        except Exception:
            pass

        return True, "Button mapping injected and active!"

    except Exception as e:
        logger.error(f"Failed applying remapper preset: {e}")
        return False, str(e)


def is_service_active() -> bool:
    """Check if system input-remapper service is running."""
    try:
        res = subprocess.run(
            ["systemctl", "is-active", "input-remapper.service"],
            capture_output=True,
            text=True,
            timeout=1
        )
        return res.stdout.strip() == "active"
    except Exception:
        return False
