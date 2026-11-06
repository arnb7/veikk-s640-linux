#!/usr/bin/env python3
"""Helper script to install VEIKK S640 input-remapper preset."""

import os
import shutil
import subprocess

SOURCE_PRESET = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "config", "input-remapper", "default.json"
)

TARGET_DIR = os.path.expanduser("~/.config/input-remapper-2/presets/VEIKK S640 Buttons")
TARGET_PRESET = os.path.join(TARGET_DIR, "default.json")


def main():
    print(f"[*] Installing input-remapper preset for 'VEIKK S640 Buttons'...")
    os.makedirs(TARGET_DIR, exist_ok=True)
    shutil.copyfile(SOURCE_PRESET, TARGET_PRESET)
    print(f"[+] Preset installed to: {TARGET_PRESET}")

    print("\n[*] To start the preset or enable autoload:")
    print("    1. Ensure input-remapper service is active:")
    print("       sudo systemctl restart input-remapper")
    print("    2. Apply preset manually:")
    print("       input-remapper-control --command start --device 'VEIKK S640 Buttons' --preset default")
    print("    3. Enable autoload on plug:")
    print("       input-remapper-control --command autoload")


if __name__ == "__main__":
    main()
