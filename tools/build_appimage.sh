#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
APPDIR="${REPO_ROOT}/build_appdir"
OUTPUT_APPIMAGE="${REPO_ROOT}/Veikk_Config-x86_64.AppImage"

echo "[*] Building VEIKK S640 AppImage..."
rm -rf "${APPDIR}" "${OUTPUT_APPIMAGE}"
mkdir -p "${APPDIR}/usr/bin"
mkdir -p "${APPDIR}/usr/lib/veikk_s640"
mkdir -p "${APPDIR}/usr/lib/python3/site-packages"
mkdir -p "${APPDIR}/usr/share/applications"
mkdir -p "${APPDIR}/usr/share/icons/hicolor/256x256/apps"

# 1. Copy veikk_s640 python package
cp -r "${REPO_ROOT}/veikk_s640/"* "${APPDIR}/usr/lib/veikk_s640/"

# 2. Bundle evdev and pyusb for cross-distro portability if present
python3 -c "
import shutil, os, evdev, usb
site_dst = '${APPDIR}/usr/lib/python3/site-packages'
# Copy evdev
evdev_dir = os.path.dirname(evdev.__file__)
shutil.copytree(evdev_dir, os.path.join(site_dst, 'evdev'), dirs_exist_ok=True)
# Copy usb
usb_dir = os.path.dirname(usb.__file__)
shutil.copytree(usb_dir, os.path.join(site_dst, 'usb'), dirs_exist_ok=True)
print('[*] Bundled evdev and pyusb successfully into AppDir')
"

# 3. Copy desktop entry and icon
cp "${REPO_ROOT}/config/veikk-config.desktop" "${APPDIR}/veikk-config.desktop"
cp "${REPO_ROOT}/config/veikk-config.desktop" "${APPDIR}/usr/share/applications/veikk-config.desktop"
cp "${REPO_ROOT}/config/veikk-config.png" "${APPDIR}/veikk-config.png"
cp "${REPO_ROOT}/config/veikk-config.png" "${APPDIR}/usr/share/icons/hicolor/256x256/apps/veikk-config.png"

# 4. Create AppRun launcher
cat << 'EOF' > "${APPDIR}/AppRun"
#!/bin/bash
set -e

HERE="$(dirname "$(readlink -f "${0}")")"
export APPDIR="${HERE}"
export PATH="${HERE}/usr/bin:${PATH}"
export PYTHONPATH="${HERE}/usr/lib:${HERE}/usr/lib/python3/site-packages:${HERE}/usr/lib64/python3/site-packages:${PYTHONPATH}"
export XDG_DATA_DIRS="${HERE}/usr/share:${XDG_DATA_DIRS:-/usr/local/share:/usr/share}"

if command -v python3 >/dev/null 2>&1; then
    PYTHON_BIN="python3"
elif [ -x /usr/bin/python3 ]; then
    PYTHON_BIN="/usr/bin/python3"
else
    echo "Error: Python 3 with GTK4 / Libadwaita is required to run VEIKK Tablet Settings." >&2
    exit 1
fi

exec "$PYTHON_BIN" "${HERE}/usr/bin/veikk-config" "$@"
EOF
chmod +x "${APPDIR}/AppRun"

# 5. Create usr/bin/veikk-config launcher
cat << 'EOF' > "${APPDIR}/usr/bin/veikk-config"
#!/usr/bin/env python3
import sys
import os

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__))) # usr directory
LIB_DIR = os.path.join(HERE, "lib")
SITE_DIR = os.path.join(LIB_DIR, "python3", "site-packages")

for p in (LIB_DIR, SITE_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

from veikk_s640.gui import main

if __name__ == "__main__":
    sys.exit(main())
EOF
chmod +x "${APPDIR}/usr/bin/veikk-config"

# 6. Check for appimagetool
APPIMAGETOOL="/tmp/appimagetool"
if [ ! -x "${APPIMAGETOOL}" ]; then
    if command -v appimagetool >/dev/null 2>&1; then
        APPIMAGETOOL="$(command -v appimagetool)"
    else
        echo "[*] Downloading appimagetool..."
        curl -sLo /tmp/appimagetool https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage
        chmod +x /tmp/appimagetool
        APPIMAGETOOL="/tmp/appimagetool"
    fi
fi

# 7. Build AppImage
echo "[*] Packaging AppImage using ${APPIMAGETOOL}..."
ARCH=x86_64 "${APPIMAGETOOL}" --appimage-extract-and-run "${APPDIR}" "${OUTPUT_APPIMAGE}"

echo "[✓] Successfully built: ${OUTPUT_APPIMAGE}"
ls -lh "${OUTPUT_APPIMAGE}"
rm -rf "${APPDIR}"
