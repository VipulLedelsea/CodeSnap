"""Single entry point for Code Capture.

Runs the local web app by default. When invoked with --capture it runs the
hotkey capture worker instead (the web app launches this on 'Start capture').

This one-binary dispatch is what lets the whole thing be bundled into a macOS
.app: the frozen executable re-invokes itself with --capture instead of trying
to spawn a separate `python hotkey_capture.py`.

  python main.py            # web app (default)
  python main.py --capture  # capture worker (usually launched by the web app)
  python main.py --capture --single   # capture worker, single-agent backup
"""

import sys


def main() -> int:
    if "--capture" in sys.argv:
        import hotkey_capture
        # drop --capture, keep the rest (e.g. --single) for hotkey_capture's argparse
        sys.argv = [sys.argv[0]] + [a for a in sys.argv[1:] if a != "--capture"]
        return hotkey_capture.main()
    from webapp.server import main as web_main
    return web_main() or 0


if __name__ == "__main__":
    raise SystemExit(main())
