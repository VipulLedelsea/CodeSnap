import hashlib
from pathlib import Path

from PIL import Image
import pytest
from fastapi.testclient import TestClient

from core.model import ProgramStore
from core.model.restitch import rebuild_saved_capture

SOURCE = (Path(__file__).parent / 'samples/cobol/AIDCALC.cbl').read_text()


@pytest.fixture
def saved(tmp_path, monkeypatch):
    monkeypatch.setenv('CODESNAP_PROGRAMS', str(tmp_path / 'programs'))
    with ProgramStore.create('Saved source') as store:
        evidence = store.add_evidence(_png(tmp_path))
        aid = store.add_artifact('AIDCALC.cbl', language='COBOL', transcription='broken', evidence_ids=[evidence])
        store.set_status(aid, 'structured')
        frame = store.evidence(evidence)
        cache = store.text_cache_dir / (frame['sha256'] + '.md')
        cache.write_text(SOURCE)
        store.set_meta('deepdive', {str(aid): {'facts': ['stale facts']}})
        yield store, aid, evidence, cache


def _png(tmp_path):
    p = tmp_path / 'shot.png'
    Image.new('RGB', (40, 20), 'red').save(p)
    return p


def test_rebuild_preserves_photos_cache_and_old_version_without_api(saved, monkeypatch):
    store, aid, evidence, cache = saved
    from webapp import server
    monkeypatch.setattr(server, '_client', lambda: pytest.fail('No API client should be used'))
    frame = Path(store.evidence(evidence)['abs_path'])
    before = hashlib.sha256(frame.read_bytes()).hexdigest()
    response = TestClient(server.app).post(f'/api/programs/{store.info["slug"]}/artifacts/{aid}/rebuild')
    assert response.status_code == 200, response.text
    result = response.json()
    assert result['api_cost'] == 0 and result['version'] == 2
    assert store.artifact(aid)['transcription'] == 'broken'
    current = store.artifact(result['artifact_id'])
    assert current['status'] == 'structured'
    assert 'PROGRAM-ID. AIDCALC.' in current['transcription']
    assert store.artifact_evidence(result['artifact_id'])[0]['id'] == evidence
    assert hashlib.sha256(frame.read_bytes()).hexdigest() == before
    assert cache.read_text() == SOURCE
    assert str(aid) not in (store.get_meta('deepdive') or {})


def test_missing_cache_makes_no_changes(saved):
    store, aid, _, cache = saved
    cache.unlink()
    with pytest.raises(ValueError, match='not cached'):
        rebuild_saved_capture(store, aid)
    assert len(store.artifacts(False)) == 1
    assert store.artifact(aid)['transcription'] == 'broken'


def test_rebuild_cannot_restore_removed_file(saved):
    store, aid, _, _ = saved
    store.delete_artifact(aid)
    with pytest.raises(KeyError):
        rebuild_saved_capture(store, aid)
    assert store.artifacts() == []


def test_active_review_blocks_rebuild(saved, monkeypatch):
    store, aid, _, _ = saved
    from webapp import server
    monkeypatch.setitem(server._DEEP, store.info['slug'], {'running': True})
    response = TestClient(server.app).post(f'/api/programs/{store.info["slug"]}/artifacts/{aid}/rebuild')
    assert response.status_code == 409
    assert len(store.artifacts(False)) == 1


def test_rebuild_progress_is_visible_and_removed_after_completion(saved, monkeypatch):
    import threading
    from webapp import server
    from core.model import restitch
    store, aid, _, _ = saved
    entered, release = threading.Event(), threading.Event()
    original = restitch.rebuild_saved_capture

    def paused(st, artifact_id, progress=None):
        progress(stage='Stitching saved text', done=1, total=1)
        entered.set()
        assert release.wait(10)
        return original(st, artifact_id, progress=progress)

    monkeypatch.setattr(restitch, 'rebuild_saved_capture', paused)
    client = TestClient(server.app)
    base = f'/api/programs/{store.info["slug"]}'
    result = []
    worker = threading.Thread(target=lambda: result.append(client.post(f'{base}/artifacts/{aid}/rebuild')))
    worker.start()
    try:
        assert entered.wait(10)
        data = client.get(base).json()
        assert data['artifacts'][0]['state'] == 'reading'
        assert data['artifacts'][0]['rebuild']['stage'] == 'Stitching saved text'
        assert data['progress']['reading'] == 1
        assert data['progress']['finished'] == 0
        assert client.post(f'{base}/artifacts/{aid}/rebuild').status_code == 409
        assert client.delete(f'{base}/artifacts/{aid}').status_code == 409
    finally:
        release.set()
        worker.join(10)
    assert result[0].status_code == 200
    data = client.get(base).json()
    assert 'rebuild' not in data['artifacts'][0]
    assert data['progress']['reading'] == 0


def test_rebuild_error_clears_processing_state(saved):
    from webapp import server
    store, aid, _, cache = saved
    cache.unlink()
    base = f'/api/programs/{store.info["slug"]}'
    client = TestClient(server.app)
    assert client.post(f'{base}/artifacts/{aid}/rebuild').status_code == 409
    assert store.info['slug'] not in server._REBUILDS
    assert client.get(base).json()['progress']['reading'] == 0


def test_rebuild_extracts_source_from_truncated_response(saved):
    import json
    store, aid, _, cache = saved
    cache.write_text('{"raw_transcription": ' + json.dumps(SOURCE.splitlines()) + ', "corrections": [')
    r = rebuild_saved_capture(store, aid)
    assert 'raw_transcription' not in store.artifact(r['artifact_id'])['transcription']
    assert 'PROGRAM-ID. AIDCALC.' in store.artifact(r['artifact_id'])['transcription']


def test_correction_rebase_uses_owning_paragraph():
    from core.model.restitch import _correction_positions
    class Store:
        def corrections(self):
            return [{'id': 1, 'op': 'artifact.replace_line', 'payload': {
                'artifact': 'test.cbl', 'line': 3, 'old_text': '           END-IF.',
                'new_text': '           END-IF'}}]
    old = '1000-FIRST.\n MOVE A TO B\n           END-IF\n2000-NEXT.\n MOVE A TO B\n           END-IF.'
    new = '0500-NEW.\n MOVE C TO D\n1000-FIRST.\n MOVE A TO B\n           END-IF.\n2000-NEXT.\n MOVE A TO B\n           END-IF.'
    assert _correction_positions(Store(), {'name': 'test.cbl', 'transcription': old}, new)[0][1] == 5


def test_correction_rebase_refuses_ambiguous_rows():
    from core.model.restitch import _correction_positions
    class Store:
        def corrections(self):
            return [{'id': 1, 'op': 'artifact.confirm_line', 'payload': {
                'artifact': 'x', 'line': 1, 'old_text': 'END'}}]
    with pytest.raises(ValueError, match='Cannot safely relocate'):
        _correction_positions(Store(), {'name': 'x', 'transcription': 'END'}, 'END\nEND')


def test_correction_rebase_preserves_spaces_inside_bms_literals():
    from core.model.restitch import _correction_positions
    class Store:
        def corrections(self):
            return [{'id': 1, 'op': 'artifact.replace_line', 'payload': {
                'artifact': 'map.bms', 'line': 1,
                'old_text': "DFHMDF INITIAL='LABEL      '",
                'new_text': "DFHMDF INITIAL='LABEL    '"}}]
    art = {'name': 'map.bms', 'transcription': "DFHMDF INITIAL='LABEL    '"}
    # The three-space value is neither the original nor the accepted correction.
    code = "DFHMDF INITIAL='LABEL   '\n    DFHMDF INITIAL='LABEL      '"
    assert _correction_positions(Store(), art, code)[0][1] == 2
    with pytest.raises(ValueError, match='Cannot safely relocate'):
        _correction_positions(Store(), art, "DFHMDF INITIAL='LABEL   '")


def test_bms_source_can_rebuild_even_when_classified_as_screen(saved):
    store, aid, _, cache = saved
    source = (Path(__file__).parent / 'samples/cobol/AIDMAP.bms').read_text()
    store.rename_artifact(aid, 'AIDMAP.bms')
    store.fill_artifact(aid, artifact_type='ui_screen', language='CICS BMS map', transcription=source, status='structured')
    cache.write_text(source)
    result = rebuild_saved_capture(store, aid)
    assert 'DFHMSD' in store.artifact(result['artifact_id'])['transcription']


def test_rebuild_refuses_file_changed_during_processing(saved):
    store, aid, _, _ = saved
    def progress(**state):
        if state['stage'] == 'Saving rebuilt analysis':
            store.fill_artifact(aid, artifact_type='code', language='COBOL', transcription='accepted new edit', status='structured')
    with pytest.raises(ValueError, match='file changed'):
        rebuild_saved_capture(store, aid, progress)
    assert store.artifact(aid)['transcription'] == 'accepted new edit'
    assert len(store.artifacts(False)) == 1
