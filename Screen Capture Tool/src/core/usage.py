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


def cost(model: str, input_tokens, output_tokens, *, cache_write_tokens=0, cache_read_tokens=0, cache_write_1h_tokens=0):
    price = price_for(model)
    if price is None or input_tokens is None or output_tokens is None:
        return None
    read_rate = 0.05 if model.startswith('claude-opus-5-5') else 0.025 if model.startswith('claude-fable-5-1') else 0.1
    weighted = input_tokens + cache_write_tokens * 1.25 + cache_write_1h_tokens * 2 + cache_read_tokens * read_rate
    return round((weighted * price[0] + output_tokens * price[1]) / 1_000_000, 6)


def cached_request(kwargs):
    """Cache stable tools/system prefix, leaving changing screenshot content uncached."""
    import os
    import copy
    if os.environ.get('CODESNAP_PROMPT_CACHE', '1').lower() in ('0', 'false', 'off'):
        return kwargs
    if not str(kwargs.get('model', '')).startswith('claude-'):
        return kwargs
    def marked(value):
        if isinstance(value, dict):
            return 'cache_control' in value or any(marked(v) for v in value.values())
        return isinstance(value, list) and any(marked(v) for v in value)
    if marked(kwargs):
        return kwargs  # preserve caller breakpoints and TTLs, including the four-point limit
    system = kwargs.get('system')
    if isinstance(system, str) and system:
        system = [{'type': 'text', 'text': system}]
    elif isinstance(system, list) and system and system[-1].get('type') == 'text':
        system = copy.deepcopy(system)
    else:
        return kwargs
    system[-1]['cache_control'] = {'type': 'ephemeral'}
    return {**kwargs, 'system': system}


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
        self.on_record = None

    def bucket(self):
        return getattr(self._local, "bucket", None) or self.default_bucket

    def set_thread_bucket(self, bucket):
        self._local.bucket = bucket

    def record(self, step, model, usage, ms, ok=True, error=None):
        input_tokens = getattr(usage, "input_tokens", None) if usage is not None else None
        output_tokens = getattr(usage, "output_tokens", None) if usage is not None else None
        created = getattr(usage, 'cache_creation_input_tokens', 0) or 0
        read = getattr(usage, 'cache_read_input_tokens', 0) or 0
        details = getattr(usage, 'cache_creation', None)
        hour = (details.get('ephemeral_1h_input_tokens', 0) if isinstance(details, dict)
                else getattr(details, 'ephemeral_1h_input_tokens', 0)) or 0
        hour = min(hour, created)
        billed_cost = cost(model, input_tokens, output_tokens, cache_write_tokens=created-hour,
                           cache_write_1h_tokens=hour, cache_read_tokens=read)
        if input_tokens is not None:
            input_tokens += created + read
        import uuid
        rec = {"call_id": uuid.uuid4().hex, "bucket": self.bucket(), "step": step, "model": model, "input_tokens": input_tokens,
               "output_tokens": output_tokens, "cost": billed_cost, "ms": ms,
               "cache_creation_input_tokens": created, "cache_read_input_tokens": read,
               "cache_creation_1h_input_tokens": hour,
               "ok": ok, "error": error}
        with self._lock:
            self._records.append(rec)
            self.total_cost += rec["cost"] or 0
        if self.on_record:
            self.on_record(rec)
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
    out = {"calls": 0, "input_tokens": 0, "output_tokens": 0, "cost": 0.0, "by_step": {},
           "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0}
    for r in records:
        out["calls"] += 1
        out["input_tokens"] += r.get("input_tokens") or 0
        out["output_tokens"] += r.get("output_tokens") or 0
        out["cost"] += r.get("cost") or 0
        for key in ('cache_creation_input_tokens', 'cache_read_input_tokens'):
            out[key] += r.get(key) or 0
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
        kwargs = cached_request(kwargs)
        try:
            msg = self._messages.create(**kwargs)
        except Exception as exc:
            self._tracker.record(step, kwargs.get("model"), None, int((time.monotonic() - began) * 1000),
                                 ok=False, error=f"{type(exc).__name__}: {exc}")
            raise
        record = self._tracker.record(step, getattr(msg, "model", None) or kwargs.get("model"), getattr(msg, "usage", None),
                             int((time.monotonic() - began) * 1000),
                             ok=getattr(msg, "stop_reason", None) != "max_tokens",
                             error="output truncated (max_tokens)" if getattr(msg, "stop_reason", None) == "max_tokens" else None)
        if self._tracker.on_record:
            # Pydantic provider models accept private attributes via object assignment.
            object.__setattr__(msg, "_codesnap_usage_record", record)
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


class SavedBudget:
    """Check durable spending before every call, including calls made by another worker."""
    def __init__(self, program):
        self.program = program

    def check(self, tracker):
        from core.model import ProgramStore
        with ProgramStore.open(self.program) as store:
            limit = program_budget(store)
            spent = store.usage()["cost"]
        if limit and spent >= limit:
            raise BudgetExceeded(f"API budget reached: ${spent:.2f} of ${limit:.2f} spent on this program.")


def persist_record(program, record, artifact_id=None):
    from core.model import ProgramStore
    with ProgramStore.open(program) as store:
        store.log_usage_record(record, artifact_id=artifact_id)


def program_client(program, client):
    tracker = UsageTracker()
    tracker.budget = SavedBudget(program)
    tracker.budget.check(tracker)
    tracker.on_record = lambda record: persist_record(program, record)
    return tracker.wrap(client)
