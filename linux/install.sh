#!/bin/bash
# Add Harry Spotter to your applications menu, with its icon.
# Run it from the extracted HarrySpotter folder:   ./install.sh
# (Optional - the app also runs straight from this folder: ./HarrySpotter)
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
APPS="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
mkdir -p "$APPS"
cat > "$APPS/harryspotter.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Harry Spotter
Comment=Time-resolved and apo density inspector
Exec="$DIR/HarrySpotter"
Path=$DIR
Icon=$DIR/_internal/harryspotter_logo.png
Terminal=false
Categories=Science;Education;
EOF
chmod +x "$APPS/harryspotter.desktop"
command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$APPS" >/dev/null 2>&1 || true
echo "Harry Spotter added to your applications menu."
echo "If you move this folder, run ./install.sh again."
