#!/bin/bash
# Double-click after closing the laptop or quitting the app: picks up any run still waiting on its batches.
cd "$(dirname "$0")" || exit 1
[ -d "$HOME/sct-venv" ] && source "$HOME/sct-venv/bin/activate" || source ".venv/bin/activate"
export CODESNAP_BATCH=1 CODESNAP_PIPELINE=staged
caffeinate -ims env PYTHONPATH=src python src/resume.py
read -r -p "Done. Press Return to close."
