#!/bin/bash
# Build Harry Spotter for Linux and package it as a .tar.gz.
#   Needs: Python 3 with Tkinter (e.g. sudo apt install python3-tk) and
#          python3 -m pip install pyinstaller pillow
#   Result: HarrySpotter-<version>-Linux-<arch>.tar.gz
set -e
cd "$(dirname "$0")"
VERSION="${VERSION:-3.3}"
ARCH="$(uname -m)"

python3 -m PyInstaller --noconfirm HarrySpotter-linux.spec

STAGE="package/HarrySpotter-$VERSION"
rm -rf package
mkdir -p "$STAGE"
cp -r dist/HarrySpotter/. "$STAGE/"
cp linux/install.sh linux/README_FIRST.txt "$STAGE/"
chmod +x "$STAGE/HarrySpotter" "$STAGE/install.sh"
tar -czf "HarrySpotter-$VERSION-Linux-$ARCH.tar.gz" -C package "HarrySpotter-$VERSION"
rm -rf package
echo "Built: HarrySpotter-$VERSION-Linux-$ARCH.tar.gz"
