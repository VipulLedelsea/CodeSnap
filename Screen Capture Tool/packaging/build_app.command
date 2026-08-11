#!/bin/bash
# Double-click (or run) to rebuild Code Capture.app with the latest code.
# Builds -> strips extended attributes -> ad-hoc signs, so the hotkey works.
cd "$(dirname "$0")/.." || exit 1
echo "==> Rebuilding Code Capture.app ..."

# use the off-iCloud venv if present (much faster), else the local one
if [ -d "$HOME/sct-venv" ]; then source "$HOME/sct-venv/bin/activate"
elif [ -d ".venv" ]; then source ".venv/bin/activate"
fi

python -c "import PyInstaller" 2>/dev/null || pip install -q pyinstaller

pyinstaller --noconfirm packaging/CodeCapture.spec || { echo "BUILD FAILED"; read -r -p "Press Return to close."; exit 1; }

echo "==> Cleaning attributes + signing ..."
xattr -cr "dist/Code Capture.app"
codesign --force --deep --sign - "dist/Code Capture.app"

echo ""
echo "==> Done: dist/Code Capture.app"
echo "    Reminder: after a rebuild, re-grant permissions to Code Capture in"
echo "    System Settings > Privacy & Security  (Accessibility, Input Monitoring, Screen Recording),"
echo "    then reopen the app."
read -r -p "Press Return to close."
