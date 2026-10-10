#!/usr/bin/env bash
# Prepare the AUR package base "vrgb" for a release.
#
#   packaging/aur/update-aur.sh VERSION [PKGREL] OUTDIR [--build]
#
# Copies PKGBUILD and the .install files to OUTDIR, sets pkgver/pkgrel,
# pins sha256sums to the GitHub tarball of tag vVERSION and writes .SRCINFO.
# With --build it also builds both packages (no install) as a sanity check.
# Needs an Arch environment (makepkg) and must not run as root.
set -euo pipefail

VERSION=${1:?version, e.g. 1.0.1}
PKGREL=${2:-1}
OUT=${3:?output directory}
BUILD=${4:-}
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)

[[ $VERSION =~ ^[0-9]+(\.[0-9]+)*$ ]] || { echo "bad version: $VERSION" >&2; exit 1; }
[[ $PKGREL =~ ^[0-9]+$ ]] || { echo "bad pkgrel: $PKGREL" >&2; exit 1; }

mkdir -p "$OUT"
cp "$HERE/PKGBUILD" "$HERE/vrgb.install" "$HERE/vrgb-gui.install" "$OUT/"
cd "$OUT"

url="https://github.com/vrgb-dev/vrgb/archive/refs/tags/v$VERSION.tar.gz"
sum=$(curl -fsSL "$url" | sha256sum | cut -d' ' -f1)

sed -i -e "s/^pkgver=.*/pkgver=$VERSION/" \
       -e "s/^pkgrel=.*/pkgrel=$PKGREL/" \
       -e "s/^sha256sums=.*/sha256sums=('$sum')/" PKGBUILD
makepkg --printsrcinfo > .SRCINFO

if [[ $BUILD == --build ]]; then
    # Runtime dependencies (python-pyqt6, ...) are not needed to build.
    makepkg --nodeps --noconfirm -f
    rm -rf src pkg ./*.tar.gz
fi
grep -E '^\s*(pkgver|pkgrel|sha256sums) =' .SRCINFO
