#!/usr/bin/env bash

set -e

echo "VRGB Uninstaller"
echo "----------------"

echo "[1/4] Removing binary..."

if [ -f /usr/local/bin/vrgb ]; then
    sudo rm /usr/local/bin/vrgb
    echo "Removed /usr/local/bin/vrgb"
else
    echo "Binary not found. Skipping."
fi

echo "[2/4] Removing udev rule..."

if [ -f /etc/udev/rules.d/99-vrgb.rules ]; then
    sudo rm /etc/udev/rules.d/99-vrgb.rules
    echo "Removed udev rule."
else
    echo "Udev rule not found. Skipping."
fi

echo "[3/4] Reloading udev rules..."

sudo udevadm control --reload-rules
sudo udevadm trigger

echo "[4/4] Removing KDE autostart (if present)..."

if [ -f ~/.config/autostart/vrgb.desktop ]; then
    rm ~/.config/autostart/vrgb.desktop
    echo "Removed KDE autostart entry."
else
    echo "Autostart entry not found. Skipping."
fi

echo
echo "Uninstall complete."
echo
echo "Note:"
echo "The 'vrgb' group was NOT removed."
echo "You may remove it manually if desired:"
echo
echo "    sudo groupdel vrgb"
