#!/bin/bash
# Builds Ohmwork.app: a double-clickable, Dock-able macOS app that opens
# Terminal running ../../launch-ui.command (all the actual launch logic
# lives there, not here). Rebuild this any time the project folder moves,
# or to regenerate the icon.
#
# Usage: ./build_app.sh [output_dir] [project_dir]
#   output_dir  where to put Ohmwork.app (default: this repo's parent dir,
#               i.e. alongside the project folder, e.g. the Desktop)
#   project_dir the ohmwork project root the app should launch (default:
#               this script's own repo)
#
# Needs: iconutil, sips (both ship with macOS), and Pillow for the icon
# artwork (not a project dependency -- see make_icon.py's own docstring).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
OUT_DIR="${1:-$(dirname "$REPO_DIR")}"
PROJECT_DIR="${2:-$REPO_DIR}"
APP="$OUT_DIR/Ohmwork.app"

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

echo "Generating icon artwork..."
python3 "$SCRIPT_DIR/make_icon.py" "$WORK/icon_1024.png"

echo "Building .iconset..."
mkdir -p "$WORK/AppIcon.iconset"
for size in 16 32 64 128 256 512 1024; do
    sips -z "$size" "$size" "$WORK/icon_1024.png" --out "$WORK/AppIcon.iconset/icon_${size}x${size}.png" >/dev/null
done
for size in 16 32 128 256 512; do
    dbl=$((size * 2))
    sips -z "$dbl" "$dbl" "$WORK/icon_1024.png" --out "$WORK/AppIcon.iconset/icon_${size}x${size}@2x.png" >/dev/null
done
iconutil -c icns "$WORK/AppIcon.iconset" -o "$WORK/AppIcon.icns"

echo "Assembling $APP..."
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cp "$WORK/AppIcon.icns" "$APP/Contents/Resources/AppIcon.icns"

cat > "$APP/Contents/MacOS/Ohmwork" <<EOF
#!/bin/bash
open -a Terminal "$PROJECT_DIR/launch-ui.command"
EOF
chmod +x "$APP/Contents/MacOS/Ohmwork"

cat > "$APP/Contents/Info.plist" <<'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key>
    <string>Ohmwork</string>
    <key>CFBundleDisplayName</key>
    <string>Ohmwork</string>
    <key>CFBundleIdentifier</key>
    <string>com.ohmwork.launcher</string>
    <key>CFBundleVersion</key>
    <string>1.0</string>
    <key>CFBundleShortVersionString</key>
    <string>1.0</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>CFBundleExecutable</key>
    <string>Ohmwork</string>
    <key>CFBundleIconFile</key>
    <string>AppIcon</string>
    <key>LSMinimumSystemVersion</key>
    <string>11.0</string>
    <key>NSHighResolutionCapable</key>
    <true/>
</dict>
</plist>
EOF

touch "$APP"
/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister -f "$APP" >/dev/null 2>&1 || true

echo "Built $APP -- points at $PROJECT_DIR/launch-ui.command"
