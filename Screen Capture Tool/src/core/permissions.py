"""The two macOS permissions CodeSnap cannot work without, and a way to ask for them.

Screen Recording: without it a capture is an empty desktop with no windows in it, and nothing says so.
Accessibility:    without it the global hotkey listener starts and never hears a key.
Both are granted to the app (CodeSnap.app when bundled) in System Settings > Privacy & Security. Off macOS, or when a check cannot be
made, a permission is reported as None (unknown) and nothing is shown to the person."""
import subprocess
import sys

PANES = {
    "screen": "x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture",
    "accessibility": "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility",
}


def screen_recording():
    if sys.platform != "darwin":
        return None
    try:
        import Quartz
        return bool(Quartz.CGPreflightScreenCaptureAccess())
    except Exception:  # noqa: BLE001 - macOS before 10.15 or no Quartz: unknown
        return None


def accessibility():
    if sys.platform != "darwin":
        return None
    try:
        from ApplicationServices import AXIsProcessTrusted
        return bool(AXIsProcessTrusted())
    except Exception:  # noqa: BLE001
        return None


def status() -> dict:
    return {"screen": screen_recording(), "accessibility": accessibility()}


def missing() -> list:
    return [name for name, ok in status().items() if ok is False]


def request(pane: str) -> bool:
    """Show the system prompt (Screen Recording) and open the matching System Settings pane. Only the two known panes can be opened."""
    url = PANES.get(pane)
    if url is None or sys.platform != "darwin":
        return False
    if pane == "screen":
        try:
            import Quartz
            Quartz.CGRequestScreenCaptureAccess()
        except Exception:  # noqa: BLE001
            pass
    try:
        subprocess.run(["open", url], check=False, timeout=10)
        return True
    except Exception:  # noqa: BLE001
        return False
