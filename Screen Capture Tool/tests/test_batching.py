import threading
import time
from types import SimpleNamespace as NS

import pytest

from core import batching
from core.usage import UsageTracker


@pytest.fixture(autouse=True)
def _journal(tmp_path, monkeypatch):
    monkeypatch.setenv("CODESNAP_BATCH_JOURNAL", str(tmp_path / "default-journal.json"))


class FakeBatches:
    def __init__(self, fail=None):
        self.created, self.fail, self.polls = [], fail or {}, 0

    def create(self, requests):
        self.created.append(requests)
        return NS(id=f"b{len(self.created)}")

    def retrieve(self, batch_id):
        self.polls += 1
        return NS(id=batch_id, processing_status="ended" if self.polls > 1 else "in_progress")

    def results(self, batch_id):
        out = []
        for r in self.created[int(batch_id[1:]) - 1]:
            cid = r["params"]["messages"][0]["content"]
            if cid in self.fail:
                out.append(NS(custom_id=r["custom_id"], result=NS(type=self.fail[cid], error=NS(error="boom"))))
            else:
                msg = NS(model=r["params"]["model"], stop_reason="end_turn", content=[NS(type="text", text=f"re:{cid}")],
                         usage=NS(input_tokens=1000, output_tokens=100, cache_creation_input_tokens=0, cache_read_input_tokens=0))
                out.append(NS(custom_id=r["custom_id"], result=NS(type="succeeded", message=msg)))
        return out


def fake_client(**kw):
    messages = NS(batches=FakeBatches(**kw), create=lambda **k: (_ for _ in ()).throw(AssertionError("direct call")))
    return NS(messages=messages)


def ask(bm, text, out, i):
    out[i] = bm.create(model="claude-sonnet-4-5", max_tokens=10, messages=[{"role": "user", "content": text}], timeout=5)


def test_concurrent_calls_share_one_batch_and_return_in_order():
    client = fake_client()
    bm = batching.BatchMessages(client, window=0.3, poll=0.01)
    out = {}
    threads = [threading.Thread(target=ask, args=(bm, f"q{i}", out, i)) for i in range(5)]
    [t.start() for t in threads]
    [t.join(5) for t in threads]
    assert len(client.messages.batches.created) == 1
    assert {i: out[i].content[0].text for i in out} == {i: f"re:q{i}" for i in range(5)}
    assert all("timeout" not in r["params"] for r in client.messages.batches.created[0])


def test_failed_request_is_retried_once_then_raises():
    client = fake_client(fail={"bad": "errored"})
    bm = batching.BatchMessages(client, window=0.05, poll=0.01)
    with pytest.raises(batching.BatchRequestError):
        bm.create(model="m", max_tokens=1, messages=[{"role": "user", "content": "bad"}])
    assert len(client.messages.batches.created) == 2


def test_tracker_halves_the_cost(monkeypatch):
    monkeypatch.setenv("CODESNAP_BATCH", "1")
    monkeypatch.setattr(batching, "_SHARED", {})
    client = fake_client()
    client.api_key = "k"
    monkeypatch.setenv("CODESNAP_BATCH_WINDOW", "0.05")
    monkeypatch.setenv("CODESNAP_BATCH_POLL", "0.01")
    tracker = UsageTracker()
    batch_cost = None
    tracked = tracker.wrap(client)
    tracked.messages.create(model="claude-sonnet-4-5", max_tokens=10, system="x", messages=[{"role": "user", "content": "q"}])
    rec = tracker.take(everything=True)[0]
    from core.usage import cost
    full = cost("claude-sonnet-4-5", 1000, 100)
    if full is not None:
        assert rec["cost"] == pytest.approx(full * 0.5, rel=0.05)
    assert rec["ok"]


def test_disabled_by_default(monkeypatch):
    monkeypatch.delenv("CODESNAP_BATCH", raising=False)
    assert not batching.enabled()
    assert batching.workers(3) == 3


class ShuffledBatches(FakeBatches):
    def results(self, batch_id):
        return list(reversed(super().results(batch_id)))


def test_results_never_cross_between_files_or_programs(monkeypatch):
    monkeypatch.setenv("CODESNAP_BATCH", "1")
    monkeypatch.setattr(batching, "_SHARED", {})
    monkeypatch.setenv("CODESNAP_BATCH_WINDOW", "0.3")
    monkeypatch.setenv("CODESNAP_BATCH_POLL", "0.01")
    client = NS(messages=NS(batches=ShuffledBatches()), api_key="same-key")
    trackers = {name: UsageTracker() for name in ("program-a", "program-b")}
    clients = {name: t.wrap(client) for name, t in trackers.items()}
    got, lock = {}, threading.Lock()

    def one(program, n):
        text = f"{program}|file{n}|{'secret-' + program + str(n)}"
        msg = clients[program].messages.create(model="claude-sonnet-4-5", max_tokens=10, system="s",
                                               messages=[{"role": "user", "content": text}])
        with lock:
            got[(program, n)] = (text, msg.content[0].text)

    threads = [threading.Thread(target=one, args=(p, n)) for p in trackers for n in range(12)]
    [t.start() for t in threads]
    [t.join(10) for t in threads]
    assert len(got) == 24
    assert len(client.messages.batches.created) == 1
    assert all(reply == f"re:{text}" for text, reply in got.values())
    for name, tracker in trackers.items():
        assert len(tracker.take(everything=True)) == 12


def test_restarted_app_collects_an_earlier_batch_without_paying_twice(tmp_path):
    journal = tmp_path / "journal.json"
    never = FakeBatches()
    never.retrieve = lambda bid: NS(id=bid, processing_status="in_progress")
    first = batching.BatchMessages(NS(messages=NS(batches=never)), window=0.05, poll=0.01)
    first.journal = batching.Journal(journal)
    t = threading.Thread(target=lambda: first.create(model="m", max_tokens=1, messages=[{"role": "user", "content": "keep me"}]), daemon=True)
    t.start()
    for _ in range(100):
        if journal.exists():
            break
        time.sleep(0.02)
    assert journal.exists() and len(never.created) == 1

    done = FakeBatches()
    done.created = list(never.created)
    done.polls = 5
    second = batching.BatchMessages(NS(messages=NS(batches=done)), window=0.05, poll=0.01)
    second.journal = batching.Journal(journal)
    msg = second.create(model="m", max_tokens=1, messages=[{"role": "user", "content": "keep me"}])
    assert msg.content[0].text == "re:keep me"
    assert len(done.created) == 1
    assert batching.Journal(journal).get(batching.request_key(
        {"model": "m", "max_tokens": 1, "messages": [{"role": "user", "content": "keep me"}]})) is None


def test_polling_survives_a_sleeping_laptop():
    client = fake_client()
    real = client.messages.batches.retrieve
    state = {"n": 0}

    def flaky(bid):
        state["n"] += 1
        if state["n"] <= 2:
            raise ConnectionError("network is down")
        return real(bid)
    client.messages.batches.retrieve = flaky
    bm = batching.BatchMessages(client, window=0.05, poll=0.01)
    import core.batching as B
    orig = B.time.sleep
    B.time.sleep = lambda s: orig(0.01)
    try:
        msg = bm.create(model="m", max_tokens=1, messages=[{"role": "user", "content": "x"}])
    finally:
        B.time.sleep = orig
    assert msg.content[0].text == "re:x"


def test_rejected_request_is_a_bad_request_not_retried():
    from core.batching import BatchBadRequest
    from core import deepdive
    assert BatchBadRequest in deepdive._bad_request_types()
