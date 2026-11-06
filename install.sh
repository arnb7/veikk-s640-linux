#!/usr/bin/env bash
# ==============================================================================
# VEIKK S640 Open-Source Userspace Driver & udev Installer for Fedora
# ==============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ "$EUID" -ne 0 ]; then
    echo "[-] Please run this installer with sudo: sudo ./install.sh"
    exit 1
fi

REAL_USER="${SUDO_USER:-$USER}"
REAL_HOME=$(getent passwd "$REAL_USER" | cut -d: -f6)

echo "[*] Installing VEIKK S640 Linux Driver for user: $REAL_USER"

# 0. Ensure system dependencies are installed
echo "[*] Installing required system packages (python3-pyusb, evtest, python3-evdev)..."
dnf install -y python3-pyusb evtest python3-evdev

# Disable conflicting proprietary vktablet if present (prevents cursor fighting/jumping)
echo "[*] Disabling conflicting proprietary vktablet..."
killall -9 vktablet 2>/dev/null || true
rm -f /etc/xdg/autostart/vktablet.desktop 2>/dev/null || true
rm -f /usr/share/applications/vktablet.desktop 2>/dev/null || true
rm -f /usr/bin/vktablet 2>/dev/null || true
chmod -x /usr/lib/vktablet/vktablet 2>/dev/null || true

# 1. Install udev rules
echo "[*] Installing udev rules to /etc/udev/rules.d/99-veikk-s640.rules..."
cp "$SCRIPT_DIR/udev/99-veikk-s640.rules" /etc/udev/rules.d/99-veikk-s640.rules
udevadm control --reload-rules
udevadm trigger

# 2. Install Configuration
echo "[*] Installing configuration to /etc/veikk-s640/config.toml..."
mkdir -p /etc/veikk-s640
cp "$SCRIPT_DIR/config/config.toml" /etc/veikk-s640/config.toml

# 3. Install Python package and executables
echo "[*] Installing driver binaries to /usr/local/bin/..."
mkdir -p /usr/local/lib
cp -r "$SCRIPT_DIR/veikk_s640" /usr/local/lib/
cp "$SCRIPT_DIR/bin/veikk-s640d" /usr/local/bin/veikk-s640d
cp "$SCRIPT_DIR/bin/veikk-config" /usr/local/bin/veikk-config
chmod +x /usr/local/bin/veikk-s640d /usr/local/bin/veikk-config
chmod 666 /etc/veikk-s640/config.toml 2>/dev/null || true

# Install Desktop Application entry
echo "[*] Installing GUI settings app to /usr/share/applications/vktablet.desktop..."
cp "$SCRIPT_DIR/config/vktablet.desktop" /usr/share/applications/vktablet.desktop
cp "$SCRIPT_DIR/config/vktablet.desktop" /usr/share/applications/veikk-config.desktop

# 4. Install systemd service
echo "[*] Installing systemd service /etc/systemd/system/veikk-s640.service..."
cp "$SCRIPT_DIR/systemd/veikk-s640.service" /etc/systemd/system/veikk-s640.service
systemctl daemon-reload
systemctl enable veikk-s640.service
systemctl restart veikk-s640.service

# 5. Install input-remapper presets and autoload for the desktop user
if [ -d "$REAL_HOME" ]; then
    echo "[*] Installing input-remapper 2.x presets for $REAL_USER..."
    mkdir -p "$REAL_HOME/.config/input-remapper-2/presets/VEIKK S640 Buttons"
    mkdir -p "$REAL_HOME/.config/input-remapper-2/presets/VEIKK S640 Pen"
    cp "$SCRIPT_DIR/config/input-remapper/default.json" "$REAL_HOME/.config/input-remapper-2/presets/VEIKK S640 Buttons/default.json"
    cp "$SCRIPT_DIR/config/input-remapper/default.json" "$REAL_HOME/.config/input-remapper-2/presets/VEIKK S640 Pen/default.json"
    
    # Configure input-remapper autoload
    python3 -c "
import json, os
cfg_file = os.path.expanduser('$REAL_HOME/.config/input-remapper-2/config.json')
data = {'version': '2.2.1', 'autoload': {}}
if os.path.isfile(cfg_file):
    try:
        with open(cfg_file, 'r') as f: data = json.load(f)
    except Exception: pass
if 'autoload' not in data or not isinstance(data['autoload'], dict):
    data['autoload'] = {}
data['autoload']['VEIKK S640 Pen'] = 'default'
with open(cfg_file, 'w') as f:
    json.dump(data, f, indent=4)
" 2>/dev/null || true

    mkdir -p "$REAL_HOME/.config/veikk-s640"
    if [ ! -f "$REAL_HOME/.config/veikk-s640/config.toml" ]; then
        cp "$SCRIPT_DIR/config/config.toml" "$REAL_HOME/.config/veikk-s640/config.toml"
    fi
    chown -R "$REAL_USER:$REAL_USER" "$REAL_HOME/.config/input-remapper-2" "$REAL_HOME/.config/veikk-s640"

    # Reload input-remapper autoload
    sudo -u "$REAL_USER" input-remapper-control --command autoload 2>/dev/null || true
fi

echo ""
echo "[+] VEIKK S640 driver installed and service started!"
echo "    - System service: systemctl status veikk-s640"
echo "    - View live logs: journalctl -u veikk-s640 -f"
echo "    - Configuration GUI: veikk-config (or launch 'VEIKK Tablet Settings' from App Menu)"
echo ""
echo "[*] To test pen movement across the entire screen:"
echo "    1. Plug in your VEIKK S640 tablet."
echo "    2. Run 'veikk-config' to fine-tune smoothness, pressure curves, and active area."
echo "    3. Test with evtest: sudo evtest (select 'VEIKK S640 Pen')"
