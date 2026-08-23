#!/bin/bash
# Double-click (or run) to rebuild CodeSnap.app with the latest code.
# Builds -> strips extended attributes -> ad-hoc signs, so the hotkey works.
cd "$(dirname "$0")/.." || exit 1
echo "==> Rebuilding CodeSnap.app ..."

# use the off-iCloud venv if present (much faster), else the local one
if [ -d "$HOME/sct-venv" ]; then source "$HOME/sct-venv/bin/activate"
elif [ -d ".venv" ]; then source ".venv/bin/activate"
fi

python -c "import PyInstaller" 2>/dev/null || pip install -q pyinstaller

pyinstaller --noconfirm packaging/CodeSnap.spec || { echo "BUILD FAILED"; read -r -p "Press Return to close."; exit 1; }

echo "==> Cleaning attributes + signing ..."
xattr -cr "dist/CodeSnap.app"
codesign --force --deep --sign - "dist/CodeSnap.app"

echo ""
echo "==> Done: dist/CodeSnap.app"
echo "    Reminder: after a rebuild, re-grant permissions to CodeSnap in"
echo "    System Settings > Privacy & Security  (Accessibility, Input Monitoring, Screen Recording),"
echo "    then reopen the app."
read -r -p "Press Return to close."
