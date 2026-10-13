"""A quick call to each model a run will use, so a wrong model name or missing access fails in seconds instead of
hours into a batch. Uses the plain client (never the batch client) and one output token."""
import os
import time

_OK = {}          # model -> when it last answered
TTL = 600.0


def reading_models() -> list:
    from core import analysis
    return [analysis.PLAIN_MODEL, analysis.READ_MODEL]


def analysis_models() -> list:
    from core import analysis, deepdive, neighbor, pipeline
    return [pipeline.DRAFT_MODEL, pipeline.FINAL_MODEL, deepdive.DEFAULT_DEEP_MODEL, deepdive.DEFAULT_REVIEW_MODEL,
            os.environ.get("CODESNAP_DEEP_MODEL"), neighbor.MODEL]


def check_models(client, models, now=None) -> list:
    """[(model, reason)] for each distinct model that does not answer; [] when every one does."""
    now = time.monotonic() if now is None else now
    plain = getattr(client, "_client", client)
    failed = []
    for model in dict.fromkeys(m for m in models if m):
        if now - _OK.get(model, -TTL) < TTL:
            continue
        try:
            plain.messages.create(model=model, max_tokens=1, messages=[{"role": "user", "content": "ok"}])
            _OK[model] = now
        except Exception as exc:  # noqa: BLE001
            code = getattr(exc, "status_code", None)
            failed.append((model, f"{type(exc).__name__}{f' ({code})' if code else ''}: {str(exc)[:160]}"))
    return failed


def describe(failed) -> str:
    return "Model check failed before the run: " + "; ".join(f"{m}: {why}" for m, why in failed) \
        + ". Fix the model name or access, then start again."
