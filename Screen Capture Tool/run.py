#!/usr/bin/env python3
"""One-command setup + launch for Code Capture.

Run this once after cloning — it creates a virtual environment, installs the
dependencies, asks for your Anthropic API key the first time, and starts the app.

    python3 run.py            # set up, then run the app (opens your browser)
    python3 run.py --build    # set up, then build the double-click macOS .app
    python3 run.py --setup    # set up only, don't launch

Uses only the Python standard library, so it runs on a fresh machine.
"""

import argparse
import os
import subprocess
import sys
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV = ROOT / ".venv"
REQ = ROOT / "requirements.txt"


def _venv_python() -> Path:
    return VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def step(msg: str) -> None:
    print(f"\n==> {msg}")


def ensure_python() -> None:
    if sys.version_info < (3, 10):
        sys.exit(f"Python 3.10+ required (you have {sys.version_info.major}.{sys.version_info.minor}).")


def ensure_venv() -> None:
    if _venv_python().exists():
        step("Using existing virtual environment (.venv)")
        return
    step("Creating virtual environment (.venv) ...")
    venv.EnvBuilder(with_pip=True).create(VENV)


def install_deps() -> None:
    step("Installing dependencies ...")
    py = str(_venv_python())
    subprocess.check_call([py, "-m", "pip", "install", "-q", "--upgrade", "pip"])
    subprocess.check_call([py, "-m", "pip", "install", "-q", "-r", str(REQ)])


def ensure_api_key() -> None:
    if os.environ.get("ANTHROPIC_API_KEY"):
        step("API key found in environment")
        return
    env_file = ROOT / ".env"
    candidates = [env_file, Path.home() / ".code_capture" / ".env"]
    for f in candidates:
        try:
            if f.exists() and "ANTHROPIC_API_KEY" in f.read_text():
                step(f"API key found in {f}")
                return
        except OSError:
            pass
    step("Anthropic API key needed")
    print("  Get one at https://console.anthropic.com/  (it starts with 'sk-ant-').")
    key = input("  Paste your ANTHROPIC_API_KEY: ").strip()
    if not key:
        sys.exit("No key entered — re-run when you have one.")
    env_file.write_text(f"ANTHROPIC_API_KEY={key}\n")
    print(f"  Saved to {env_file}  (git-ignored — stays on your machine).")


def run_app() -> None:
    step("Starting Code Capture — your browser will open ...")
    subprocess.call([str(_venv_python()), str(ROOT / "src" / "main.py")], cwd=str(ROOT))


def build_app() -> None:
    if sys.platform != "darwin":
        sys.exit("Building the .app is macOS-only. Use 'python3 run.py' to run it instead.")
    step("Building the macOS .app (PyInstaller) ...")
    py = str(_venv_python())
    subprocess.check_call([py, "-m", "pip", "install", "-q", "pyinstaller"])
    subprocess.check_call([py, "-m", "PyInstaller", "--noconfirm", "packaging/CodeCapture.spec"], cwd=str(ROOT))
    app = ROOT / "dist" / "Code Capture.app"
    subprocess.call(["xattr", "-cr", str(app)])
    subprocess.call(["codesign", "--force", "--deep", "--sign", "-", str(app)])
    print(f"\nBuilt: {app}")
    print("  Drag it to /Applications, then grant Screen Recording + Accessibility + Input Monitoring.")


def main() -> int:
    ap = argparse.ArgumentParser(description="Set up and run Code Capture.")
    ap.add_argument("--build", action="store_true", help="build the double-click macOS .app instead of running")
    ap.add_argument("--setup", action="store_true", help="set up the environment but don't launch")
    args = ap.parse_args()

    print("Code Capture — setup")
    ensure_python()
    ensure_venv()
    install_deps()
    ensure_api_key()

    if args.build:
        build_app()
    elif args.setup:
        step("Setup complete. Run 'python3 run.py' to start.")
    else:
        run_app()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
