import threading
import time
from types import SimpleNamespace

from fastapi.testclient import TestClient

from test_line_review import reviewed  # noqa: F401  (a program with one flagged file)
from core import deepdive
from core.usage import BucketPool, UsageTracker


def _answer(client, base, new_text=None):
    d = client.get(base).json()
    return client.post(base, json={'text_hash': d['text_hash'], 'old_text': d['old_text'],
                                   'new_text': d['old_text'] if new_text is None else new_text})


def test_a_file_can_be_answered_while_other_files_are_still_being_analysed(reviewed, monkeypatch):
    from webapp import server
    store, aid, _ = reviewed
    slug = store.info['slug']
    other = store.add_artifact('OTHER.cbl', language='COBOL', transcription='X\n')
    store.set_status(other, 'structured')
    store.set_meta('deepdive_active', {str(other): time.time()})          # another file is in a batch right now
    monkeypatch.setitem(server._DEEP, slug, {'running': True})            # and a review is running
    stopped = []
    monkeypatch.setattr(server, '_stop_analysis', lambda *a, **k: stopped.append(1) or True)
    client = TestClient(server.app)
    response = _answer(client, f'/api/programs/{slug}/artifacts/{aid}/review/20')
    assert response.status_code == 200, response.text
    assert not stopped                                                    # the running analysis is left alone


def test_the_file_being_reviewed_itself_is_not_changed_underneath_the_review(reviewed, monkeypatch):
    from webapp import server
    store, aid, _ = reviewed
    store.set_meta('deepdive_active', {str(aid): time.time()})
    client = TestClient(server.app)
    response = _answer(client, f'/api/programs/{store.info["slug"]}/artifacts/{aid}/review/20')
    assert response.status_code == 409 and 'reviewed right now' in response.json()['detail']
    assert not store.corrections()


def test_a_corrected_file_waits_for_the_running_review_then_is_reviewed(reviewed, monkeypatch):
    from webapp import server
    store, aid, _ = reviewed
    slug = store.info['slug']
    started = []
    monkeypatch.setattr(server, '_deep_start', lambda s, ids=None: started.append(ids) or {})
    monkeypatch.setattr(server, 'api_key_status', lambda: {'has_key': True})
    monkeypatch.setattr(server, '_deep_watch', lambda *a, **k: None)
    monkeypatch.setattr('core.model.line_review.items', lambda *a, **k: [])
    monkeypatch.setattr(deepdive, 'pending', lambda s: [store.artifact(aid)])
    monkeypatch.setitem(server._DEEP, slug, {'running': True})
    server._deep_when_ready(slug, aid)
    time.sleep(1.5)
    assert server._DEEP_QUEUE[slug] == {aid} and not started             # queued, not started on top of the run
    server._DEEP[slug] = {'running': False}
    server._deep_drain(slug)
    assert started == [[aid]]


def test_analysis_gate_admits_as_many_as_its_capacity():
    from hotkey_capture import _AnalysisGate
    gate = _AnalysisGate()
    live, peak, lock = [0], [0], threading.Lock()

    def work():
        with gate:
            with lock:
                live[0] += 1
                peak[0] = max(peak[0], live[0])
            time.sleep(0.05)
            with lock:
                live[0] -= 1
    threads = [threading.Thread(target=work) for _ in range(6)]
    for t in threads: t.start()
    for t in threads: t.join()
    assert peak[0] == 1                                                  # a plain lock by default
    gate.set_capacity(4)
    peak[0] = 0
    threads = [threading.Thread(target=work) for _ in range(8)]
    for t in threads: t.start()
    for t in threads: t.join()
    assert 2 <= peak[0] <= 4


def test_pool_workers_charge_the_file_that_submitted_them():
    tracker = UsageTracker()
    seen = []

    def job():
        seen.append(tracker.bucket())

    def file(name):
        tracker.set_thread_bucket(name)
        with BucketPool(max_workers=2) as pool:
            list(pool.map(lambda _: job(), range(3)))
        tracker.set_thread_bucket(None)
    a = threading.Thread(target=file, args=('file-a',))
    b = threading.Thread(target=file, args=('file-b',))
    a.start(); b.start(); a.join(); b.join()
    assert sorted(seen) == ['file-a'] * 3 + ['file-b'] * 3


class _Batches:
    """A batch that never ends on its own: it ends (canceled) only once cancel is called."""
    def __init__(self):
        self.cancelled = False

    def create(self, requests):
        return SimpleNamespace(id='b1')

    def retrieve(self, batch_id):
        return SimpleNamespace(processing_status='ended' if self.cancelled else 'in_progress')

    def cancel(self, batch_id):
        self.cancelled = True

    def results(self, batch_id):
        return [SimpleNamespace(custom_id='r0', result=SimpleNamespace(type='canceled'))]


class _Messages:
    def __init__(self):
        self.batches = _Batches()
        self.live = []

    def stream(self, **params):
        outer = self

        class Stream:
            def __enter__(self_):
                return self_

            def __exit__(self_, *exc):
                return False

            def get_final_message(self_):
                outer.live.append(params)
                return SimpleNamespace(content=[], usage=None, stop_reason='end_turn')
        return Stream()


def test_a_batch_that_runs_too_long_is_cancelled_and_its_requests_go_out_live(tmp_path, monkeypatch):
    from core import batching
    monkeypatch.setenv('CODESNAP_BATCH_JOURNAL', str(tmp_path / 'journal.json'))
    messages = _Messages()
    batch = batching.BatchMessages(SimpleNamespace(messages=messages), window=0.01, poll=0.01, timeout=0.05)
    msg = batch.create(model='m', max_tokens=10, messages=[{'role': 'user', 'content': 'hi'}], timeout=600)
    assert messages.batches.cancelled and len(messages.live) == 1
    assert getattr(msg, '_codesnap_live', False)                         # recorded at full price, not the batch discount
    assert 'timeout' not in messages.live[0]
