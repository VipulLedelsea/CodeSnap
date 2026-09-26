import threading
import time

PRICES = {
    "claude-opus-5-5": (4.0, 20.0),
    "claude-sonnet-5": (2.0, 10.0),
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-haiku-4-5": (1.0, 5.0),
    "claude-fable-5-1": (10.0, 50.0),
}


def price_for(model: str):
    model = model or ""
    for key in sorted(PRICES, key=len, reverse=True):
        if model.startswith(key):
            return PRICES[key]
    return None


def cost(model: str, input_tokens, output_tokens):
    price = price_for(model)
    if price is None or input_tokens is None or output_tokens is None:
        return None
    return round((input_tokens * price[0] + output_tokens * price[1]) / 1_000_000, 6)


_STEPS = None


def _step_table():
    global _STEPS
    if _STEPS is None:
        table = []
        try:
            from core import analysis
            table += [(analysis.EXTRACT_JSON_SYSTEM_PROMPT, "transcribe"), (analysis.EXTRACT_SYSTEM_PROMPT, "transcribe"),
                      (analysis.EXTRACT_INDENT_SYSTEM_PROMPT, "transcribe"), (analysis.FINALIZE_SYSTEM_PROMPT, "classify"),
                      (analysis.FIX_SYSTEM_PROMPT, "fix"), (analysis.EXPLAIN_SYSTEM_PROMPT, "explain_error"),
                      (analysis.INDENT_REVIEW_SYSTEM, "indent_review"), (analysis.SYSTEM_PROMPT, "analyse")]
        except Exception:
            pass
        try:
            import team
            table += [(team.ANALYST_SYSTEM, "analyst"), (team.DIAGRAMMER_SYSTEM, "diagram")]
        except Exception:
            pass
        try:
            from core.cobol.columns import COLUMN_REVIEW_SYSTEM
            from core.model.extract import STRUCTURE_SYSTEM
            from core.project import PROJECT_SYSTEM
            from core.extractors.ui import UI_SYSTEM
            table += [(COLUMN_REVIEW_SYSTEM, "column_review"), (STRUCTURE_SYSTEM, "structure"),
                      (PROJECT_SYSTEM, "project_map"), (UI_SYSTEM, "ui_screen")]
        except Exception:
            pass
        _STEPS = {text: name for text, name in table if isinstance(text, str)}
    return _STEPS


def step_for(system) -> str:
    if isinstance(system, list):
        system = "".join(b.get("text", "") for b in system if isinstance(b, dict))
    if not system:
        return "other"
    table = _step_table()
    if system in table:
        return table[system]
    for text, name in table.items():
        if system.startswith(text[:120]):
            return name
    return "other"


class BudgetExceeded(RuntimeError):
    pass


class Budget:
    """Per-program API spend cap. `spent` is what the program had already spent when the budget was attached."""

    def __init__(self, limit: float, spent: float = 0.0, warn_at: float = 0.8, on_warn=None):
        self.limit, self.base, self.warn_at, self.on_warn = float(limit), float(spent or 0), warn_at, on_warn
        self.warned = False

    def check(self, tracker):
        total = self.base + tracker.total_cost
        if total >= self.limit:
            raise BudgetExceeded(f"API budget reached: ${total:.2f} of ${self.limit:.2f} spent on this program. "
                                 f"Raise the budget in the program settings to continue.")
        if not self.warned and total >= self.warn_at * self.limit:
            self.warned = True
            if self.on_warn:
                self.on_warn(total, self.limit)


def program_budget(store):
    import os
    limit = store.get_meta("budget_usd")
    if limit in (None, "", 0):
        env = os.environ.get("CODESNAP_PROGRAM_BUDGET_USD")
        limit = float(env) if env else None
    return float(limit) if limit else None


class UsageTracker:
    def __init__(self):
        self._lock = threading.Lock()
        self._records = []
        self.total_cost = 0.0
        self.budget = None
        self._local = threading.local()
        self.default_bucket = None

    def bucket(self):
        return getattr(self._local, "bucket", None) or self.default_bucket

    def set_thread_bucket(self, bucket):
        self._local.bucket = bucket

    def record(self, step, model, usage, ms, ok=True, error=None):
        input_tokens = getattr(usage, "input_tokens", None) if usage is not None else None
        output_tokens = getattr(usage, "output_tokens", None) if usage is not None else None
        extra = sum(getattr(usage, k, 0) or 0 for k in ("cache_creation_input_tokens", "cache_read_input_tokens")) \
            if usage is not None else 0
        if input_tokens is not None:
            input_tokens += extra
        rec = {"bucket": self.bucket(), "step": step, "model": model, "input_tokens": input_tokens,
               "output_tokens": output_tokens, "cost": cost(model, input_tokens, output_tokens), "ms": ms,
               "ok": ok, "error": error}
        with self._lock:
            self._records.append(rec)
            self.total_cost += rec["cost"] or 0
        return rec

    def take(self, bucket=None, everything=False):
        with self._lock:
            keep, out = [], []
            for r in self._records:
                (out if everything or r["bucket"] == bucket else keep).append(r)
            self._records = keep
        return out

    def wrap(self, client):
        return TrackedClient(client, self)


def summarize(records) -> dict:
    out = {"calls": 0, "input_tokens": 0, "output_tokens": 0, "cost": 0.0, "by_step": {}}
    for r in records:
        out["calls"] += 1
        out["input_tokens"] += r.get("input_tokens") or 0
        out["output_tokens"] += r.get("output_tokens") or 0
        out["cost"] += r.get("cost") or 0
        step = out["by_step"].setdefault(r["step"], {"calls": 0, "input_tokens": 0, "output_tokens": 0, "cost": 0.0})
        step["calls"] += 1
        step["input_tokens"] += r.get("input_tokens") or 0
        step["output_tokens"] += r.get("output_tokens") or 0
        step["cost"] += r.get("cost") or 0
    out["cost"] = round(out["cost"], 4)
    for step in out["by_step"].values():
        step["cost"] = round(step["cost"], 4)
    return out


class _TrackedMessages:
    def __init__(self, messages, tracker):
        self._messages = messages
        self._tracker = tracker

    def create(self, **kwargs):
        if self._tracker.budget is not None:
            self._tracker.budget.check(self._tracker)
        began = time.monotonic()
        step = step_for(kwargs.get("system"))
        try:
            msg = self._messages.create(**kwargs)
        except Exception as exc:
            self._tracker.record(step, kwargs.get("model"), None, int((time.monotonic() - began) * 1000),
                                 ok=False, error=f"{type(exc).__name__}: {exc}")
            raise
        self._tracker.record(step, getattr(msg, "model", None) or kwargs.get("model"), getattr(msg, "usage", None),
                             int((time.monotonic() - began) * 1000),
                             ok=getattr(msg, "stop_reason", None) != "max_tokens",
                             error="output truncated (max_tokens)" if getattr(msg, "stop_reason", None) == "max_tokens" else None)
        return msg

    def __getattr__(self, name):
        return getattr(self._messages, name)


class TrackedClient:
    def __init__(self, client, tracker):
        self._client = client
        self.tracker = tracker
        self.messages = _TrackedMessages(client.messages, tracker)

    def __getattr__(self, name):
        return getattr(self._client, name)
