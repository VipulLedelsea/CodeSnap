"""Foundation connectivity test — Anthropic API (direct).

Confirms the Milestone 1 foundation on the API stack:
  1. the `anthropic` package is installed,
  2. an API key is available (loaded from .env),
  3. a round-trip to the Messages API returns text.

Auth model: this script uses a CLAUDE PLATFORM API KEY (pay-as-you-go),
read from the ANTHROPIC_API_KEY entry in your .env file. This is the new
project strategy: the "brain" is the Anthropic API called directly, not the
Claude Agent SDK.

Prerequisites (one-time):
  - pip install -r requirements.txt
  - Put your key in .env:   ANTHROPIC_API_KEY=sk-ant-...
    (.env is gitignored and must never be committed.)

Run it:  python hello_api.py
You should see a short greeting printed back from the model.
"""

import os
import sys

# A current, vision-capable model. Screenshots in later milestones will use
# the same family, so keep this in one place.
MODEL = "claude-sonnet-4-6"
PROMPT = "Say hello in one short sentence."


def main() -> int:
    # Load .env if python-dotenv is present; optional if the key is already
    # exported in the environment.
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:
        pass

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print(
            "ANTHROPIC_API_KEY is not set.\n"
            "Add it to your .env file:   ANTHROPIC_API_KEY=sk-ant-...\n"
            "(or export it in your shell), then re-run.",
            file=sys.stderr,
        )
        return 1

    try:
        import anthropic
    except ImportError:
        print(
            "anthropic is not installed.\n"
            "Install dependencies first:  pip install -r requirements.txt",
            file=sys.stderr,
        )
        return 1

    client = anthropic.Anthropic(api_key=api_key)

    try:
        message = client.messages.create(
            model=MODEL,
            max_tokens=64,
            messages=[{"role": "user", "content": PROMPT}],
        )
    except Exception as exc:  # noqa: BLE001 - surface a friendly hint
        print(
            f"Could not complete the call: {type(exc).__name__}: {exc}\n\n"
            "Common fixes:\n"
            "  - Check the key in .env is valid and active\n"
            "  - Confirm the account has API credit / billing enabled\n"
            f"  - Confirm the model name is current: {MODEL}",
            file=sys.stderr,
        )
        return 1

    reply = "".join(getattr(block, "text", "") for block in message.content).strip()

    if not reply:
        print("Connected, but no text was returned.", file=sys.stderr)
        return 1

    print(reply)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
