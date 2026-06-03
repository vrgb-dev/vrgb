#!/usr/bin/env bash

set -e

# Run from the script's own directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "VRGB GUI Installer"
echo "------------------"

# 1. Require the vrgb CLI (the GUI imports it as a module + uses it for pkexec)
if [ ! -x /usr/local/bin/vrgb ]; then
    echo "The 'vrgb' CLI is not installed at /usr/local/bin/vrgb."
    echo "Run ./install.sh first, then re-run this script."
    exit 1
fi

# 2. Check PyQt6
if ! python3 -c "import PyQt6.QtWidgets" 2>/dev/null; then
    echo "PyQt6 is missing. Install it with one of:"
    echo "    sudo dnf install python3-pyqt6        # Fedora"
    echo "    pip install --user PyQt6"
    exit 1
fi

echo "[1/4] Installing GUI to /usr/local/bin/vrgb-gui ..."
sudo install -m 755 vrgb-gui.py /usr/local/bin/vrgb-gui

echo "[2/4] Installing icon ..."
if [ -f assets/vrgblogodark.png ]; then
    sudo install -m 644 assets/vrgblogodark.png /usr/share/pixmaps/vrgb.png
    # Also drop into the hicolor theme so menus/tray resolve "vrgb"
    sudo install -d /usr/share/icons/hicolor/256x256/apps
    sudo install -m 644 assets/vrgblogodark.png /usr/share/icons/hicolor/256x256/apps/vrgb.png
fi

echo "[3/4] Installing desktop launcher ..."
sudo install -m 644 vrgb-gui.desktop /usr/share/applications/vrgb-gui.desktop
sudo update-desktop-database /usr/share/applications 2>/dev/null || true
sudo gtk-update-icon-cache -f /usr/share/icons/hicolor 2>/dev/null || true

echo "[4/4] Optional: start the GUI (tray) automatically on login"
read -p "Add login autostart for the tray? (y/n): " AUTOSTART
if [[ "$AUTOSTART" == "y" || "$AUTOSTART" == "Y" ]]; then
    mkdir -p ~/.config/autostart
    cat > ~/.config/autostart/vrgb-gui.desktop <<EOF
[Desktop Entry]
Type=Application
Name=VRGB (tray)
Comment=Keyboard RGB control tray applet
Exec=/usr/local/bin/vrgb-gui --tray
Icon=vrgb
Terminal=false
X-GNOME-Autostart-enabled=true
EOF
    echo "Autostart (tray) installed."
fi

echo
echo "GUI installation complete."
echo "Launch it from your app menu (search 'VRGB') or run: vrgb-gui"
echo
echo "NOTE: For non-root keyboard access, you must be in the 'vrgb' group."
echo "If you just ran ./install.sh, log out and back in once so the group"
echo "becomes active. Until then the GUI falls back to a Polkit password"
echo "prompt (pkexec) when it writes to the keyboard."
