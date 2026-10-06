import hashlib
import json
import os
import tempfile
import threading
import time
from pathlib import Path

STRIP = ("timeout", "extra_headers", "extra_query", "extra_body", "stream")


def enabled() -> bool:
    return os.environ.get("CODESNAP_BATCH", "0").lower() in ("1", "true", "on", "yes")


def workers(default: int, batch_default: int = 12) -> int:
    return batch_default if enabled() else default


KEEP_DAYS = 27


def journal_path() -> Path:
    return Path(os.environ.get("CODESNAP_BATCH_JOURNAL") or (Path.home() / "CodeSnap" / "batch_journal.json")).expanduser()


def request_key(params) -> str:
    return hashlib.sha256(json.dumps(params, sort_keys=True, default=str).encode()).hexdigest()


class Journal:
    """Remembers which requests are already in a batch, so a restarted app collects them instead of paying twice."""
    def __init__(self, path=None):
        self.path = Path(path) if path else journal_path()
        self._lock = threading.Lock()

    def _load(self):
        try:
            data = json.loads(self.path.read_text())
        except Exception:
            return {}
        cutoff = time.time() - KEEP_DAYS * 86400
        return {k: v for k, v in data.items() if v.get("at", 0) > cutoff}

    def _save(self, data):
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=str(self.path.parent), suffix=".tmp")
            with os.fdopen(fd, "w") as fh:
                json.dump(data, fh)
            os.replace(tmp, self.path)
        except Exception:
            pass

    def get(self, key):
        with self._lock:
            return self._load().get(key)

    def put_many(self, entries):
        with self._lock:
            data = self._load()
            data.update(entries)
            self._save(data)

    def drop(self, key):
        with self._lock:
            data = self._load()
            if data.pop(key, None) is not None:
                self._save(data)


_SHARED = {}
_SHARED_LOCK = threading.Lock()


class BatchRequestError(RuntimeError):
    pass


class _Item:
    def __init__(self, params):
        self.params = params
        self.event = threading.Event()
        self.message = None
        self.error = None
        self.tries = 0
        self.key = None


class BatchMessages:
    is_batch = True

    def __init__(self, client, window=None, max_size=500, poll=None, timeout=None):
        self._client = client
        self._messages = client.messages
        self.window = float(os.environ.get("CODESNAP_BATCH_WINDOW", 5)) if window is None else window
        self.poll = float(os.environ.get("CODESNAP_BATCH_POLL", 15)) if poll is None else poll
        self.timeout = float(os.environ.get("CODESNAP_BATCH_TIMEOUT", 24 * 3600)) if timeout is None else timeout
        self.max_size = max_size
        self._queue = []
        self._cond = threading.Condition()
        self._last = 0.0
        self._thread = None
        self.journal = Journal()

    @classmethod
    def shared(cls, client):
        key = getattr(client, "api_key", None) or id(client)
        with _SHARED_LOCK:
            found = _SHARED.get(key)
            if found is None:
                found = _SHARED[key] = cls(client)
            return found

    def create(self, **kwargs):
        params = {k: v for k, v in kwargs.items() if k not in STRIP}
        item = _Item(params)
        item.key = request_key(params)
        entry = self.journal.get(item.key)
        if entry:
            threading.Thread(target=self._attach, args=(item, entry), daemon=True, name="codesnap-batch-attach").start()
        else:
            self._submit(item)
        item.event.wait()
        if item.error is not None:
            raise item.error
        self.journal.drop(item.key)
        return item.message

    def _call(self, fn, *args, patience=3600.0):
        """Retry through sleep, wifi loss and API hiccups; give up only after `patience` seconds of failures."""
        began = time.monotonic()
        wait = 5.0
        while True:
            try:
                return fn(*args)
            except Exception as exc:  # noqa: BLE001
                if getattr(exc, "status_code", None) in (400, 401, 403, 404) or time.monotonic() - began > patience:
                    raise
                time.sleep(min(wait, 120.0))
                wait *= 2

    def _wait_ended(self, batch_id):
        deadline = time.monotonic() + self.timeout
        while True:
            batch = self._call(self._messages.batches.retrieve, batch_id)
            if batch.processing_status == "ended":
                return batch
            if time.monotonic() > deadline:
                try:
                    self._messages.batches.cancel(batch_id)
                except Exception:
                    pass
                raise BatchRequestError(f"batch {batch_id} did not finish within {self.timeout:.0f}s")
            time.sleep(self.poll)

    def _attach(self, item, entry):
        try:
            self._wait_ended(entry["batch_id"])
            results = {r.custom_id: r.result for r in self._call(lambda: list(self._messages.batches.results(entry["batch_id"])))}
            res = results.get(entry["custom_id"])
        except Exception:  # noqa: BLE001
            res = None
        if getattr(res, "type", None) == "succeeded":
            item.message = res.message
            item.event.set()
            return
        self.journal.drop(item.key)
        self._submit(item)

    def _submit(self, item):
        with self._cond:
            self._queue.append(item)
            self._last = time.monotonic()
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(target=self._collect, daemon=True, name="codesnap-batch")
                self._thread.start()
            self._cond.notify_all()

    def _collect(self):
        while True:
            with self._cond:
                while not self._queue:
                    if not self._cond.wait(timeout=30):
                        if not self._queue:
                            self._thread = None
                            return
                while len(self._queue) < self.max_size and time.monotonic() - self._last < self.window:
                    self._cond.wait(timeout=max(0.05, self.window - (time.monotonic() - self._last)))
                group, self._queue = self._queue[:self.max_size], self._queue[self.max_size:]
            threading.Thread(target=self._run, args=(group,), daemon=True, name="codesnap-batch-run").start()

    def _run(self, group):
        try:
            batch = self._call(lambda: self._messages.batches.create(requests=[
                {"custom_id": f"r{i}", "params": item.params} for i, item in enumerate(group)]), patience=600.0)
            self.journal.put_many({item.key: {"batch_id": batch.id, "custom_id": f"r{i}", "at": time.time()}
                                   for i, item in enumerate(group)})
            self._wait_ended(batch.id)
            results = {r.custom_id: r.result for r in self._call(lambda: list(self._messages.batches.results(batch.id)))}
        except Exception as exc:  # noqa: BLE001
            for item in group:
                item.error = exc if isinstance(exc, BatchRequestError) else BatchRequestError(f"{type(exc).__name__}: {exc}")
                item.event.set()
            return
        retry = []
        for i, item in enumerate(group):
            res = results.get(f"r{i}")
            kind = getattr(res, "type", None)
            if kind == "succeeded":
                item.message = res.message
                item.event.set()
            elif kind in ("errored", "expired") and item.tries < 1:
                item.tries += 1
                retry.append(item)
            else:
                detail = getattr(getattr(res, "error", None), "error", None) or getattr(res, "error", None) or kind
                item.error = BatchRequestError(f"batch request {kind or 'missing'}: {detail}")
                item.event.set()
        for item in retry:
            self._submit(item)

    def __getattr__(self, name):
        return getattr(self._messages, name)
