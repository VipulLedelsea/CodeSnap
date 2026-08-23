#!/bin/bash
# Build CodeSnap.app off-iCloud, sign it ad-hoc, and zip it for a GitHub Release.
set -e
cd "$(dirname "$0")/.." || exit 1            # project root (Screen Capture Tool)
echo "==> Building CodeSnap.app for release ..."

if [ -d "$HOME/sct-venv" ]; then source "$HOME/sct-venv/bin/activate"
elif [ -d ".venv" ]; then source ".venv/bin/activate"; fi
python -c "import PyInstaller" 2>/dev/null || pip install -q pyinstaller

BUILD="$HOME/cc-build"
rm -rf "$BUILD"
pyinstaller --noconfirm --workpath "$BUILD/work" --distpath "$BUILD/dist" packaging/CodeSnap.spec

APP="$BUILD/dist/CodeSnap.app"
if [ ! -d "$APP" ]; then echo "BUILD FAILED — no .app produced"; exit 1; fi
echo "==> Cleaning attributes + ad-hoc signing ..."
xattr -cr "$APP"
codesign --force --deep --sign - "$APP"

OUT="$BUILD/CodeSnap-macOS.zip"
rm -f "$OUT"
ditto -c -k --keepParent "$APP" "$OUT"      # proper .app zip (preserves bundle)

echo ""
echo "==> Done."
echo "    App:  $APP"
echo "    Zip:  $OUT"
echo ""
echo "    Next: upload that .zip as a GitHub Release asset"
echo "    (Releases -> Draft a new release -> attach the zip)."
read -r -p "Press Return to close."
