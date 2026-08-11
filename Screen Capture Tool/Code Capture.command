#!/bin/bash
# Double-click this file (Finder) to launch Code Capture — no terminal typing needed.
# It activates the virtual environment, makes sure dependencies are installed,
# then starts the local web app and opens it in your browser.

cd "$(dirname "$0")" || exit 1
echo "Starting Code Capture..."

# Pick a virtual environment: prefer the off-iCloud one (faster), else the local .venv
if [ -d "$HOME/sct-venv" ]; then
  source "$HOME/sct-venv/bin/activate"
elif [ -d ".venv" ]; then
  source ".venv/bin/activate"
else
  echo "No virtual environment found (~/sct-venv or .venv)."
  echo "Create one first:  python3 -m venv ~/sct-venv && source ~/sct-venv/bin/activate && pip install -r requirements.txt"
  read -r -p "Press Return to close."
  exit 1
fi

# Make sure web deps are present (quiet; only installs if missing)
python -c "import fastapi, uvicorn" 2>/dev/null || python -m pip install -q -r requirements.txt

# Launch the web app (opens the browser itself)
python src/main.py

# Keep the window open if the server exits so errors are visible
echo ""
read -r -p "Server stopped. Press Return to close."
