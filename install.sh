#!/usr/bin/env bash

set -e

# This script invokes sudo only for system-wide files. Running the whole
# installer as root breaks per-user autostart paths and systemd --user state.
if [[ $EUID -eq 0 ]]; then
    echo "Error: do not run this installer with sudo/root."
    echo "Run: ./install.sh"
    echo "The installer will request sudo when it needs it."
    exit 1
fi

# Run installer from its own directory (prevents path issues)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

SUITE_LIB=/usr/local/lib/vrgb-gui

echo "VRGB Installer (v1.1.0)"
echo "---------------"

# Ensure script exists
if [ ! -f "$SCRIPT_DIR/vrgb.py" ]; then
    echo "Error: vrgb.py not found"
    exit 1
fi

# What to install: `./install.sh core|suite`, or ask.
EDITION="$1"
if [[ "$EDITION" != "core" && "$EDITION" != "suite" ]]; then
    echo "  1) VRGB Core  - the vrgb command line tool only (no dependencies)"
    echo "  2) VRGB Suite - Core + GUI and tray (PyQt6): idle auto-off, daytime-off"
    read -p "Install Core or Suite? [1/2]: " CHOICE
    [[ "$CHOICE" == "2" ]] && EDITION=suite || EDITION=core
fi

if [[ "$EDITION" == "suite" ]] && ! python3 -c "import PyQt6.QtWidgets" 2>/dev/null; then
    echo "VRGB Suite needs PyQt6. Install it with one of:"
    echo "    sudo dnf install python3-pyqt6        # Fedora"
    echo "    sudo apt install python3-pyqt6        # Debian / Ubuntu"
    echo "    sudo pacman -S python-pyqt6           # Arch"
    echo "Then re-run this script (or choose Core)."
    exit 1
fi

echo "[1/5] Installing binary..."

sudo install -m 755 vrgb.py /usr/local/bin/vrgb

echo "[2/5] Creating vrgb group (if needed)..."

sudo groupadd -f vrgb

echo "[3/5] Adding user to vrgb group..."

sudo usermod -aG vrgb "$USER"

echo "[4/5] Installing udev rule..."

# 70- so the uaccess tag is applied (it must sort before 73-seat-late.rules)
sudo install -m 644 packaging/70-vrgb.rules /etc/udev/rules.d/70-vrgb.rules
sudo rm -f /etc/udev/rules.d/99-vrgb.rules   # rule name used before v0.4

echo "[5/5] Reloading udev rules..."

sudo udevadm control --reload-rules
sudo udevadm trigger

if [[ "$EDITION" == "suite" ]]; then
    echo
    echo "[Suite 1/3] Installing the GUI to $SUITE_LIB ..."
    sudo rm -rf "$SUITE_LIB/vrgb_suite"
    sudo install -d "$SUITE_LIB/vrgb_suite"
    sudo install -m 644 suite/vrgb_suite/*.py "$SUITE_LIB/vrgb_suite/"
    sudo install -Dm644 suite/data/vrgb.png "$SUITE_LIB/data/vrgb.png"
    sudo tee /usr/local/bin/vrgb-gui > /dev/null <<EOF
#!/usr/bin/env python3
import sys
sys.path.insert(0, "$SUITE_LIB")
from vrgb_suite.app import main
sys.exit(main())
EOF
    sudo chmod 755 /usr/local/bin/vrgb-gui

    echo "[Suite 2/3] Installing launcher and icon ..."
    sudo install -m 644 suite/data/vrgb-gui.desktop /usr/share/applications/vrgb-gui.desktop
    sudo rm -f /usr/share/icons/hicolor/scalable/apps/vrgb.svg
    for size in 16 24 32 48 64 128 256; do
        sudo install -Dm644 "suite/data/icons/${size}x${size}/vrgb.png" \
            "/usr/share/icons/hicolor/${size}x${size}/apps/vrgb.png"
    done
    sudo gtk-update-icon-cache -q -t /usr/share/icons/hicolor 2>/dev/null || true
    sudo update-desktop-database /usr/share/applications 2>/dev/null || true

    echo "[Suite 3/3] Installing the systemd user unit (optional autostart) ..."
    sudo install -Dm644 suite/data/vrgb-gui.service /usr/local/lib/systemd/user/vrgb-gui.service
fi

echo
if [[ "$EDITION" == "suite" ]]; then
    read -p "Start VRGB in the tray at login (restores lighting, automatic off)? (y/n): " AUTOSTART
    if [[ "$AUTOSTART" == "y" || "$AUTOSTART" == "Y" ]]; then
        mkdir -p ~/.config/autostart
        rm -f ~/.config/autostart/vrgb.desktop   # the tray restores the lighting itself
        cat <<EOF > ~/.config/autostart/vrgb-gui.desktop
[Desktop Entry]
Type=Application
Name=VRGB (tray)
Comment=Keyboard RGB tray: restores lighting at login, automatic off
Exec=vrgb-gui --tray
Icon=vrgb
Terminal=false
X-GNOME-Autostart-enabled=true
EOF
        echo "Autostart installed."
    else
        # Desktops without XDG autostart (sway, Hyprland, ...): the same via systemd
        read -p "Start the tray with a systemd user service instead (any desktop)? (y/n): " SYSTEMD_AUTOSTART
        if [[ "$SYSTEMD_AUTOSTART" == "y" || "$SYSTEMD_AUTOSTART" == "Y" ]]; then
            systemctl --user daemon-reload
            systemctl --user enable vrgb-gui.service
            echo "systemd autostart enabled (vrgb-gui.service)."
        fi
    fi
else
read -p "Restore saved lighting automatically at login? (y/n): " AUTOSTART

if [[ "$AUTOSTART" == "y" || "$AUTOSTART" == "Y" ]]; then
    # XDG autostart is init-system agnostic. Minimal WMs/compositors can
    # instead launch `vrgb restore` from their native startup config.
    mkdir -p ~/.config/autostart
    rm -f ~/.config/systemd/user/vrgb-restore.service
    cat <<EOF > ~/.config/autostart/vrgb.desktop
[Desktop Entry]
Type=Application
Exec=/usr/local/bin/vrgb restore
Hidden=false
NoDisplay=false
X-GNOME-Autostart-enabled=true
Name=VRGB Restore
Comment=Restore keyboard RGB state
EOF
    echo "XDG autostart installed."
fi
fi

echo
echo "Installation complete."
echo
echo "The logged-in user can control the keyboard right away (udev uaccess)."
echo "Group membership (for other sessions) applies after the next login."
[[ "$EDITION" == "suite" ]] && echo "Launch the GUI from your app menu (search 'VRGB') or run: vrgb-gui"
exit 0
