"""Milestone 2 — Core value end-to-end.

Takes a full-screen screenshot, sends it to the Anthropic Messages API as a
base64-encoded image block, and prints Claude's explanation.

Prerequisites:
  pip install -r requirements.txt
  ANTHROPIC_API_KEY=sk-ant-... in .env (or exported in shell)

Run it:  python capture_explain.py
         python capture_explain.py --save        # also keeps the PNG on disk
         python capture_explain.py --file foo.png  # explain an existing image
"""

import argparse
import base64
import io
import os
import sys
import tempfile
from pathlib import Path

MODEL = "claude-sonnet-4-6"

SYSTEM_PROMPT = (
    "You are a screen-reading assistant. "
    "When given a screenshot, identify the type of content visible "
    "(e.g. code editor, spreadsheet, web page, terminal, document, diagram, etc.) "
    "and give a clear, concise explanation of what is on the screen. "
    "Lead with the content type, then explain what the user is looking at."
    "If there contains text, summarize the key text content as well. "
)

USER_PROMPT = "What is on this screen? Explain it clearly."


def load_env() -> None:
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass


def capture_screenshot() -> bytes:
    """Capture the full screen and return PNG bytes."""
    import mss
    from PIL import Image

    with mss.mss() as sct:
        # Monitor index 1 is the primary display; 0 is a virtual combined monitor.
        raw = sct.grab(sct.monitors[1])

    img = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def explain_image(client, image_bytes: bytes) -> str:
    """Send image bytes to the Messages API and return the text explanation."""
    import anthropic

    b64 = base64.standard_b64encode(image_bytes).decode()

    message = client.messages.create(
        model=MODEL,
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/png",
                            "data": b64,
                        },
                    },
                    {"type": "text", "text": USER_PROMPT},
                ],
            }
        ],
    )

    return "".join(getattr(block, "text", "") for block in message.content).strip()


def main() -> int:
    parser = argparse.ArgumentParser(description="Capture and explain a screenshot.")
    parser.add_argument("--save", action="store_true", help="Save the screenshot PNG to disk.")
    parser.add_argument("--file", metavar="PATH", help="Explain an existing image instead of capturing.")
    args = parser.parse_args()

    load_env()

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print(
            "ANTHROPIC_API_KEY is not set.\n"
            "Add it to your .env file:   ANTHROPIC_API_KEY=sk-ant-...",
            file=sys.stderr,
        )
        return 1

    try:
        import anthropic
    except ImportError:
        print("anthropic not installed. Run: pip install -r requirements.txt", file=sys.stderr)
        return 1

    client = anthropic.Anthropic(api_key=api_key)

    # --- Get image bytes ---
    if args.file:
        path = Path(args.file)
        if not path.exists():
            print(f"File not found: {path}", file=sys.stderr)
            return 1
        image_bytes = path.read_bytes()
        print(f"Using image: {path}")
    else:
        try:
            import mss  # noqa: F401
            from PIL import Image  # noqa: F401
        except ImportError:
            print("mss / Pillow not installed. Run: pip install -r requirements.txt", file=sys.stderr)
            return 1

        print("Capturing screen...", end=" ", flush=True)
        image_bytes = capture_screenshot()
        print("done.")

        if args.save:
            out = Path(tempfile.mktemp(prefix="screenshot_", suffix=".png", dir="."))
            out.write_bytes(image_bytes)
            print(f"Screenshot saved to: {out}")

    # --- Send to API ---
    print("Sending to Claude...\n")
    try:
        explanation = explain_image(client, image_bytes)
    except Exception as exc:
        print(f"API call failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    print("--- Explanation ---")
    print(explanation)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
