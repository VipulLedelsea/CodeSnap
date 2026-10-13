import hashlib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from core.model import ProgramStore
from core.model.line_review import detail, _locate, question
from core import deepdive
from core.verify import REASONS
from render import render_code

SOURCE = (Path(__file__).parent / 'samples/cobol/AIDCALC.cbl').read_text()


@pytest.fixture
def reviewed(tmp_path, monkeypatch):
    monkeypatch.setenv('CODESNAP_PROGRAMS', str(tmp_path / 'programs'))
    with ProgramStore.create('Line questions') as store:
        evidence = store.add_evidence(render_code(SOURCE, tmp_path / 'source.png', font_size=18, line_numbers=True))
        aid = store.add_artifact('AIDCALC.cbl', language='COBOL', transcription=SOURCE, evidence_ids=[evidence])
        store.set_status(aid, 'structured')
        frame = store.evidence(evidence)
        (store.text_cache_dir / (frame['sha256']+'.md')).write_text(SOURCE)
        store.set_verification(aid, {'lines': 42, 'verified': 39, 'reread': 0, 'confirmed': 0, 'joined': 0, 'unchecked': 0, 'flagged': 3, 'flags': [
            {'line': 20, 'text': SOURCE.splitlines()[19], 'reason': REASONS['mismatch']},
            {'line': 21, 'text': SOURCE.splitlines()[20], 'reason': REASONS['mismatch']},
            {'line': 20, 'text': SOURCE.splitlines()[19], 'reason': REASONS['break']} ]})
        store.set_meta('deepdive', {str(aid): {'hash': deepdive._hash(SOURCE),
                        'capture_concerns': [{'line': 20, 'reason': 'wrong value'}, {'line': 21, 'reason': 'wrong character'}]}})
        yield store, aid, evidence


def test_real_screenshot_row_is_located_and_highlighted(reviewed):
    store, aid, evidence = reviewed
    d = detail(store, store.artifact(aid), 20)
    assert d['screenshots'][0]['id'] == evidence
    band = d['screenshots'][0]['band']
    assert band and 28 + 19 * 27 <= band[0] < 28 + 20 * 27
    assert d['old_text'] == SOURCE.splitlines()[19]
    assert d['context'] == [
        {'line': n, 'text': SOURCE.splitlines()[n-1], 'focus': n == 20}
        for n in (19, 20, 21)]


def test_repeated_statements_need_unique_paragraph_context():
    code = '\n'.join(['5000-FIRST.', 'IF READY', 'MOVE 1 TO VALUE', 'END-IF.',
                      '5010-SECOND.', 'IF READY', 'MOVE 1 TO VALUE', 'END-IF.'])
    assert _locate(code, 'IF READY\nMOVE 1 TO VALUE\nEND-IF.', 3) is None
    assert _locate(code, '5010-SECOND.\nIF READY\nMOVE 1 TO VALUE\nEND-IF.', 7) == 2


def test_repeated_rexx_routines_use_their_unique_owner():
    body = ['say value', 'value = value + 1'] * 5 + ['return']
    code = '\n'.join(['route18:', *body, 'route19:', *body])
    frame = '\n'.join(['route19:', *body])
    assert _locate(code, frame, 19) == 6
    assert _locate(code, '\n'.join(body), 19) is None


def test_conflicting_numeric_reading_prompts_about_trailing_zero():
    assert 'trailing zero' in question('    MOVE 10 TO VALUE', ['    MOVE 100 TO VALUE'])
    assert 'trailing zero' not in question('    MOVE 10 TO VALUE', [])


def test_confirmation_is_audited_undoable_and_keeps_unrelated_warnings(reviewed):
    from webapp import server
    from core import feedback
    store, aid, evidence = reviewed
    client = TestClient(server.app)
    base = f'/api/programs/{store.info["slug"]}/artifacts/{aid}/review/20'
    d = client.get(base).json()
    path = Path(store.evidence(evidence)['abs_path'])
    checksum = hashlib.sha256(path.read_bytes()).hexdigest()
    r = client.post(base, json={'text_hash': d['text_hash'], 'old_text': d['old_text'], 'new_text': d['old_text']})
    assert r.status_code == 200, r.text
    assert store.artifact(aid)['transcription'] == SOURCE
    assert hashlib.sha256(path.read_bytes()).hexdigest() == checksum
    flags = store.verification(aid)['flags']
    assert len(flags) == 1
    assert any(f['line'] == 21 for f in flags)
    assert not any(f['line'] == 20 for f in flags)
    assert deepdive.current_concerns(store, store.artifact(aid)) == [{'line': 21, 'reason': 'wrong character'}]
    correction = store.corrections()[0]
    assert correction['op'] == 'artifact.confirm_line'
    feedback.undo(store, correction['id'])
    assert len(store.verification(aid)['flags']) == 3
    assert len(deepdive.current_concerns(store, store.artifact(aid))) == 2


def test_edit_refreshes_source_and_rejects_stale_answers(reviewed):
    from webapp import server
    store, aid, _ = reviewed
    client = TestClient(server.app)
    base = f'/api/programs/{store.info["slug"]}/artifacts/{aid}/review/20'
    d = client.get(base).json()
    store.set_validation(aid, 'old check', False, 'outdated compiler error')
    new = d['old_text'].replace('7138.00', '7138.10')
    r = client.post(base, json={'text_hash': d['text_hash'], 'old_text': d['old_text'], 'new_text': new})
    assert r.status_code == 200, r.text
    assert store.artifact(aid)['transcription'].splitlines()[19] == new
    assert store.artifact(aid)['validation_tool'] != 'old check'
    assert 'outdated compiler error' not in store.artifact(aid)['validation_errors']
    assert client.post(base, json={'text_hash': d['text_hash'], 'old_text': d['old_text'], 'new_text': new}).status_code == 409


def test_removed_and_superseded_file_cannot_accept_answer(reviewed):
    from webapp import server
    store, aid, _ = reviewed
    client = TestClient(server.app)
    base = f'/api/programs/{store.info["slug"]}/artifacts/{aid}/review/20'
    store.add_artifact('AIDCALC.cbl', language='COBOL', transcription=SOURCE)
    assert client.get(base).status_code == 404
    assert client.post(base, json={}).status_code == 404
    store.delete_artifact(aid)
    assert client.get(base).status_code == 404


def test_unmeasurable_pixels_do_not_get_a_guessed_highlight(reviewed, monkeypatch):
    from core import colfix
    store, aid, _ = reviewed
    monkeypatch.setattr(colfix, '_measure', lambda *args: None)
    d = detail(store, store.artifact(aid), 20)
    assert d['screenshots'] and d['screenshots'][0]['band'] is None


def test_conflicting_value_is_located_by_neighbours():
    code = 'FIRST SECTION\nMOVE A TO B\nMOVE 10 TO VALUE\nMOVE C TO D\nLAST SECTION'
    frame = code.replace('MOVE 10 TO VALUE', 'MOVE 100 TO VALUE')
    assert _locate(code, frame, 3) == 2


def test_multiline_and_active_processing_answers_are_rejected(reviewed, monkeypatch):
    from webapp import server
    store, aid, _ = reviewed
    client = TestClient(server.app)
    base = f'/api/programs/{store.info["slug"]}/artifacts/{aid}/review/20'
    d = client.get(base).json()
    body = {'text_hash': d['text_hash'], 'old_text': d['old_text'], 'new_text': d['old_text']+'\nMOVE 0 TO X'}
    assert client.post(base, json=body).status_code == 400
    monkeypatch.setitem(server._REBUILDS, store.info['slug'], {'name':'AIDCALC.cbl'})
    body['new_text'] = d['old_text']
    assert client.post(base, json=body).status_code == 409
    assert not store.corrections()


def test_context_at_file_boundaries_keeps_blank_lines(reviewed):
    store, aid, _ = reviewed
    store.fill_artifact(aid, artifact_type='code', language='COBOL', transcription='FIRST\n\nLAST')
    first = detail(store, store.artifact(aid), 1)['context']
    last = detail(store, store.artifact(aid), 3)['context']
    assert first == [{'line': 1, 'text': 'FIRST', 'focus': True}, {'line': 2, 'text': '', 'focus': False}]
    assert last == [{'line': 2, 'text': '', 'focus': False}, {'line': 3, 'text': 'LAST', 'focus': True}]


def test_confirmation_rechecks_source_and_completes_review_with_separate_gap(reviewed):
    from webapp import server
    store, aid, _ = reviewed
    store.set_validation(aid, 'stale checker', False, 'line 20: stale source error')
    client = TestClient(server.app)
    base = f'/api/programs/{store.info["slug"]}/artifacts/{aid}/review/20'
    d = client.get(base).json()
    r = client.post(base, json={'text_hash': d['text_hash'], 'old_text': d['old_text'], 'new_text': d['old_text']})
    assert r.status_code == 200, r.text
    answer = r.json()
    assert answer['review_status'] == 'completed'
    assert store.artifact(aid)['validation_tool'] != 'stale checker'
    assert 'stale source error' not in store.artifact(aid)['validation_errors']
    assert answer['remaining_issues'] == []


def test_compile_errors_do_not_create_review_questions():
    from core.model import line_review
    class S:
        def verification(self, _): return {"flags": []}
        def get_meta(self, _): return {}
    art = {"id": 1, "transcription": "A\nB\nC", "validation_ok": 0, "validation_errors": "x.cbl:2: error"}
    from core.model import edges
    asked = line_review.items(S(), art)
    assert asked and all(set(i["reasons"]) <= {edges.START_ASK, edges.END_ASK} for i in asked)   # only the file's edges, nothing about the compiler


def test_gap_only_line_is_asked_as_a_gap_and_marked_missing(reviewed):
    from webapp import server
    store, aid, _ = reviewed
    client = TestClient(server.app)
    base = f'/api/programs/{store.info["slug"]}/artifacts/{aid}/review/20'
    d = client.get(base).json()
    assert d['gap'] is True
    r = client.post(base + '/missing', json={'text_hash': d['text_hash']})
    assert r.status_code == 200, r.text
    assert any(f['line'] == 20 and f['reason'] == REASONS['break'] for f in store.verification(aid)['flags'])


def test_remove_blanks_the_line_and_an_empty_answer_without_remove_is_refused(reviewed):
    from webapp import server
    store, aid, _ = reviewed
    client = TestClient(server.app)
    base = f'/api/programs/{store.info["slug"]}/artifacts/{aid}/review/20'
    d = client.get(base).json()
    before = len(store.artifact(aid)['transcription'].splitlines())
    refused = client.post(base, json={'text_hash': d['text_hash'], 'old_text': d['old_text'], 'new_text': ''})
    assert refused.status_code == 400
    r = client.post(base, json={'text_hash': d['text_hash'], 'old_text': d['old_text'], 'new_text': '', 'remove': True})
    assert r.status_code == 200, r.text
    lines = store.artifact(aid)['transcription'].splitlines()
    assert lines[19] == '' and len(lines) == before


def test_delete_removes_the_line_through_the_endpoint_and_moves_the_rest_up(reviewed):
    from webapp import server
    store, aid, _ = reviewed
    client = TestClient(server.app)
    base = f'/api/programs/{store.info["slug"]}/artifacts/{aid}/review/20'
    d = client.get(base).json()
    before = store.artifact(aid)['transcription'].splitlines()
    r = client.post(base, json={'text_hash': d['text_hash'], 'old_text': d['old_text'], 'delete': True})
    assert r.status_code == 200, r.text
    after = store.artifact(aid)['transcription'].splitlines()
    assert after == before[:19] + before[20:] and r.json()['remaining_issues'] == []
    assert store.corrections()[0]['op'] == 'artifact.delete_line'


class _Edges:
    """A store with just what the start-and-end check reads."""
    def __init__(self, confirmed_lines=None, ver=None):
        self.meta = {"confirmed_lines": confirmed_lines or {}}
        self.ver = ver or {}
        self.evidence_rows = []

    def verification(self, _):
        return self.ver

    def get_meta(self, key, default=None):
        return self.meta.get(key, default)

    def artifact_evidence(self, _):
        return self.evidence_rows


def test_start_and_end_are_proved_by_evidence_or_asked_and_a_confirmation_closes_them():
    from core.model import confirmed, edges
    sql = {"id": 1, "name": "S.sql", "artifact_type": "code", "transcription": "INSERT INTO t VALUES (1);\nINSERT INTO t VALUES (2);"}
    store = _Edges()
    got = edges.flags(store, sql)
    assert [(f["kind"], f["line"]) for f in got] == [("start", 1), ("end", 2)]        # nothing proves either edge
    cobol = {"id": 2, "name": "A.cbl", "artifact_type": "code",
             "transcription": "       IDENTIFICATION DIVISION.\n       PROGRAM-ID. A.\n       STOP RUN."}
    assert [f["kind"] for f in edges.flags(store, cobol)] == ["end"]                  # the opener proves the start
    assert edges.start_evidence({"name": "m.bms", "transcription": "MAP DFHMSD TYPE=MAP\n X DFHMDI"}) and \
        not edges.start_evidence({"name": "m.bms", "transcription": "R00 DFHMDF POS=(3,12)\n X DFHMSD TYPE=FINAL"})
    assert edges.start_evidence({"name": "J.jcl", "transcription": "//MUNNIGHT JOB (SYNTH),CLASS=A\n//STEP1 EXEC PGM=X"})
    assert not edges.start_evidence({"name": "q.py", "transcription": "    import os\nprint(1)"})   # an indented import can be mid-file
    # numbers from the editor gutter prove the start (it begins at 1) and the end (it reaches the last line)
    numbered = _Edges(ver={"numbers": True, "first_line": 1, "last_line": 2})
    assert edges.flags(numbered, sql) == []
    # the person confirms line 1 and line 2: the same signatures the line review stores
    lines = sql["transcription"].splitlines()
    done = _Edges(confirmed_lines={"S.sql": [confirmed.signature(lines, 1), confirmed.signature(lines, 2)]})
    assert edges.flags(done, sql) == []


def test_the_edge_question_is_asked_in_the_review_and_lines_missing_marks_the_file_for_recapture(reviewed):
    from webapp import server
    from core import deepdive
    from core.model import edges
    store, aid, _ = reviewed
    art = store.artifact(aid)
    asked = [i for i in line_review_items(store, art) if edges.END_ASK in i["reasons"]]
    assert asked and asked[0]["gap"] is True
    client = TestClient(server.app)
    base = f'/api/programs/{store.info["slug"]}/artifacts/{aid}/review/{asked[0]["line"]}'
    d = client.get(base).json()
    assert d["question"] == edges.END_ASK
    assert client.post(base + "/missing", json={"text_hash": d["text_hash"]}).status_code == 200
    quality = deepdive.capture_quality(store, store.artifact(aid))
    assert any(i["kind"] == "partial" and "end of the file" in i["reason"] for i in quality["issues"])


def line_review_items(store, art):
    from core.model import line_review
    return line_review.items(store, art)
