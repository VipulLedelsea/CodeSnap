"""macOS notifications via osascript (so prompts reach the user without the terminal)."""

import subprocess


def notify(title: str, message: str) -> None:
    """Show a macOS notification + publish to the session status stream. Never raises."""
    try:
        from core import status
        status.publish(message)
    except Exception:  # noqa: BLE001
        pass
    msg = (message or "").replace('"', "'")
    ttl = (title or "").replace('"', "'")
    try:
        subprocess.run(
            ["osascript", "-e", f'display notification "{msg}" with title "{ttl}"'],
            check=False, capture_output=True, timeout=10,
        )
    except Exception:  # noqa: BLE001 - notifications are optional
        pass
