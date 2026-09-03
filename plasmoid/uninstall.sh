#!/bin/sh
# Remove the VRGB Plasma 6 applet for the current user.
set -e

APPLET_ID="org.vrgb.keyboard"
APPLET_DIR="$HOME/.local/share/plasma/plasmoids/$APPLET_ID"

echo "VRGB Widget Uninstaller"
echo "-----------------------"

echo "[1/2] Removing Plasma applet..."

if ! command -v kpackagetool6 >/dev/null 2>&1; then
    echo "kpackagetool6 not found - nothing to remove."
    exit 0
fi

if kpackagetool6 --type Plasma/Applet --list 2>/dev/null | grep -qx "$APPLET_ID"; then
    kpackagetool6 --type Plasma/Applet --remove "$APPLET_ID"
    echo "Removed $APPLET_ID"
else
    echo "Widget not installed. Skipping."
fi

echo "[2/2] Checking for leftovers..."

# kpackagetool6 normally clears this itself; catch a half-removed package.
if [ -d "$APPLET_DIR" ]; then
    rm -rf "$APPLET_DIR"
    echo "Removed leftover package directory."
else
    echo "No leftover directory. Skipping."
fi

echo
echo "Uninstall complete."
echo
echo "Note:"
echo "If the widget was on a panel, restart Plasma to clear its placeholder:"
echo
echo "    systemctl --user restart plasma-plasmashell"
echo
echo "Your vrgb profiles were NOT removed. They belong to vrgb, not the widget,"
echo "and remain available from the CLI:"
echo
echo "    vrgb profile list"
echo
echo "The vrgb CLI itself is removed by the uninstaller one level up (../uninstall.sh)."
