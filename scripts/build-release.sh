#!/usr/bin/env bash
# Stamps version into Core, Suite and installer scripts; builds release artifacts into dist/.
# Manual release helper: run only after physical hardware validation.
set -euo pipefail

version="${1:?usage: $0 VERSION}"
cd "$(dirname "$0")/.."

sed -i "s/^VERSION = \".*\"/VERSION = \"$version\"/" vrgb.py
sed -i "s/^__version__ = \"[^\"]*\"/__version__ = \"$version\"/" suite/vrgb_suite/__init__.py
sed -i -E "s/(VRGB Installer \(v)[^)]*(\))/\1$version\2/" install.sh
sed -i -E "s/(VRGB Uninstaller \(v)[^)]*(\))/\1$version\2/" uninstall.sh

rm -rf dist
python3 -m pip install --quiet build
python3 -m build --outdir dist .
python3 -m build --outdir dist suite
install -m 755 vrgb.py "dist/vrgb-$version.py"
