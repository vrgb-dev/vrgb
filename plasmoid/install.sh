#!/bin/sh
# Install or upgrade the VRGB Plasma 6 applet for the current user.
set -e

APPLET_ID="org.vrgb.keyboard"
PACKAGE_DIR="$(cd "$(dirname "$0")" && pwd)/package"

if ! command -v kpackagetool6 >/dev/null 2>&1; then
    echo "kpackagetool6 not found - this applet requires Plasma 6." >&2
    exit 1
fi

if ! command -v vrgb >/dev/null 2>&1 && [ ! -x /usr/local/bin/vrgb ]; then
    echo "Warning: vrgb was not found. Install it first with ../install.sh" >&2
fi

if kpackagetool6 --type Plasma/Applet --list 2>/dev/null | grep -qx "$APPLET_ID"; then
    echo "Upgrading $APPLET_ID..."
    kpackagetool6 --type Plasma/Applet --upgrade "$PACKAGE_DIR"
else
    echo "Installing $APPLET_ID..."
    kpackagetool6 --type Plasma/Applet --install "$PACKAGE_DIR"
fi

echo
echo "Done. Add it with: right-click the panel -> Add Widgets -> \"VRGB Keyboard Lighting\""
echo "If you upgraded an already-running applet, restart plasmashell to reload it:"
echo "  systemctl --user restart plasma-plasmashell"
