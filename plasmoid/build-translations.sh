#!/bin/sh
# Compile po/*.po into the applet package.
#
# Plasma looks up an applet's catalogue under the domain
# plasma_applet_<plugin-id>, and KPackage adds the installed package's own
# contents/locale directory to the search path, so the .mo files ship with
# the widget instead of needing root access to /usr/share/locale.
set -e

DOMAIN="plasma_applet_org.vrgb.keyboard"
BASE="$(cd "$(dirname "$0")" && pwd)"

found=0
for po in "$BASE"/po/*.po; do
    [ -e "$po" ] || continue
    found=1
    lang="$(basename "$po" .po)"
    dest="$BASE/package/contents/locale/$lang/LC_MESSAGES"
    mkdir -p "$dest"
    msgfmt --check -o "$dest/$DOMAIN.mo" "$po"
    printf '%s -> %s\n' "$lang" "${dest#"$BASE"/}/$DOMAIN.mo"
done

if [ "$found" -eq 0 ]; then
    echo "No po/*.po files found. Run ./extract-messages.sh first." >&2
    exit 1
fi

echo
echo "Now reinstall the applet so the catalogues are picked up:"
echo "  ./install.sh"
