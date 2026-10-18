#!/bin/bash
# Build CodeSnap.app off-iCloud, sign it, and package it as a .zip and a drag-to-Applications .dmg.
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

# A disk image people open and drag CodeSnap into Applications from.
DMG="$BUILD/CodeSnap-macOS.dmg"
STAGE="$BUILD/dmg"
rm -rf "$STAGE" "$DMG"; mkdir -p "$STAGE"
cp -R "$APP" "$STAGE/"
ln -s /Applications "$STAGE/Applications"
hdiutil create -quiet -volname "CodeSnap" -srcfolder "$STAGE" -ov -format UDZO "$DMG"
rm -rf "$STAGE"

# With an Apple Developer ID the build is signed for everyone and notarized, so Gatekeeper opens it without a warning:
#   CODESNAP_SIGN_ID="Developer ID Application: Your Name (TEAMID)" CODESNAP_NOTARY_PROFILE=<keychain profile> ./make_release.command
if [ -n "$CODESNAP_SIGN_ID" ]; then
  echo "==> Signing with $CODESNAP_SIGN_ID ..."
  codesign --force --deep --options runtime --timestamp --sign "$CODESNAP_SIGN_ID" "$APP"
  rm -f "$OUT"; ditto -c -k --keepParent "$APP" "$OUT"
  rm -rf "$STAGE"; mkdir -p "$STAGE"; cp -R "$APP" "$STAGE/"; ln -s /Applications "$STAGE/Applications"
  rm -f "$DMG"; hdiutil create -quiet -volname "CodeSnap" -srcfolder "$STAGE" -ov -format UDZO "$DMG"; rm -rf "$STAGE"
  codesign --force --sign "$CODESNAP_SIGN_ID" --timestamp "$DMG"
  if [ -n "$CODESNAP_NOTARY_PROFILE" ]; then
    echo "==> Notarizing (this takes a few minutes) ..."
    xcrun notarytool submit "$DMG" --keychain-profile "$CODESNAP_NOTARY_PROFILE" --wait && xcrun stapler staple "$DMG"
  fi
fi

echo ""
echo "==> Done."
echo "    App:  $APP"
echo "    Zip:  $OUT"
echo "    DMG:  $DMG"
echo ""
echo "    Next: send the .dmg (or upload it as a GitHub Release asset)."
echo "    Without a Developer ID, the first open needs right-click -> Open (see docs/DEPLOY.md)."
read -r -p "Press Return to close."
