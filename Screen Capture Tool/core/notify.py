"""macOS notifications via osascript (so prompts reach the user without the terminal)."""

import subprocess


def notify(title: str, message: str) -> None:
    """Show a macOS notification. Best-effort — never raises."""
    msg = (message or "").replace('"', "'")
    ttl = (title or "").replace('"', "'")
    try:
        subprocess.run(
            ["osascript", "-e", f'display notification "{msg}" with title "{ttl}"'],
            check=False, capture_output=True, timeout=10,
        )
    except Exception:  # noqa: BLE001 - notifications are optional
        pass
