#!/usr/bin/env bash

set -e

# Keep user-session cleanup in the invoking user's context.
if [[ $EUID -eq 0 ]]; then
    echo "Error: do not run this uninstaller with sudo/root."
    echo "Run: ./uninstall.sh"
    echo "The uninstaller will request sudo when it needs it."
    exit 1
fi

echo "VRGB Uninstaller (v1.1.0)"
echo "----------------"

echo "[1/5] Removing binary..."

if [ -f /usr/local/bin/vrgb ]; then
    sudo rm /usr/local/bin/vrgb
    echo "Removed /usr/local/bin/vrgb"
else
    echo "Binary not found. Skipping."
fi

if [ -e /usr/local/bin/vrgb-gui ] || [ -d /usr/local/lib/vrgb-gui ]; then
    echo "Removing VRGB Suite (GUI)..."
    systemctl --user disable --now vrgb-gui.service 2>/dev/null || true
    /usr/local/bin/vrgb-gui --quit 2>/dev/null || true   # stop the running tray via D-Bus
    sudo rm -rf /usr/local/lib/vrgb-gui
    sudo rm -f /usr/local/bin/vrgb-gui /usr/share/applications/vrgb-gui.desktop \
        /usr/share/icons/hicolor/scalable/apps/vrgb.svg /usr/local/lib/systemd/user/vrgb-gui.service
    for size in 16 24 32 48 64 128 256; do
        sudo rm -f "/usr/share/icons/hicolor/${size}x${size}/apps/vrgb.png"
    done
    rm -f ~/.config/autostart/vrgb-gui.desktop
fi

echo "[2/5] Removing udev rule..."

if [ -f /etc/udev/rules.d/70-vrgb.rules ] || [ -f /etc/udev/rules.d/99-vrgb.rules ]; then
    sudo rm -f /etc/udev/rules.d/70-vrgb.rules /etc/udev/rules.d/99-vrgb.rules
    echo "Removed udev rule."
else
    echo "Udev rule not found. Skipping."
fi

echo "[3/5] Reloading udev rules..."

sudo udevadm control --reload-rules
sudo udevadm trigger

echo "[4/5] Removing XDG autostart (if present)..."

if [ -f ~/.config/autostart/vrgb.desktop ]; then
    rm ~/.config/autostart/vrgb.desktop
    echo "Removed XDG autostart entry."
else
    echo "Autostart entry not found. Skipping."
fi

echo "[5/5] Removing systemd user autostart (if present)..."

if [ -f ~/.config/systemd/user/vrgb-restore.service ]; then
    systemctl --user disable --now vrgb-restore.service 2>/dev/null || true
    rm ~/.config/systemd/user/vrgb-restore.service
    systemctl --user daemon-reload
    echo "Removed systemd autostart entry."
else
    echo "systemd autostart entry not found. Skipping."
fi

echo
echo "Uninstall complete."
echo
echo "Note:"
echo "The 'vrgb' group was NOT removed."
echo "You may remove it manually if desired:"
echo
echo "    sudo groupdel vrgb"
