#!/bin/bash
# Build Harry Spotter for macOS -> dist/HarrySpotter.app
set -e
cd "$(dirname "$0")"
python3 -m PyInstaller --noconfirm HarrySpotter.spec
echo "Built: dist/HarrySpotter.app"
