#!/usr/bin/env bash

set -e

echo "VRGB Uninstaller (v0.3.5)"
echo "----------------"

echo "[1/5] Removing binary..."

if [ -f /usr/local/bin/vrgb ]; then
    sudo rm /usr/local/bin/vrgb
    echo "Removed /usr/local/bin/vrgb"
else
    echo "Binary not found. Skipping."
fi

echo "[2/5] Removing udev rule..."

if [ -f /etc/udev/rules.d/99-vrgb.rules ]; then
    sudo rm /etc/udev/rules.d/99-vrgb.rules
    echo "Removed udev rule."
else
    echo "Udev rule not found. Skipping."
fi

echo "[3/5] Reloading udev rules..."

sudo udevadm control --reload-rules
sudo udevadm trigger

echo "[4/5] Removing KDE autostart (if present)..."

if [ -f ~/.config/autostart/vrgb.desktop ]; then
    rm ~/.config/autostart/vrgb.desktop
    echo "Removed KDE autostart entry."
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
