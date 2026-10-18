import os
from types import SimpleNamespace

import pytest
from webapp import session


@pytest.fixture
def manager(tmp_path, monkeypatch):
    monkeypatch.setattr(session, 'PROJECT', tmp_path)
    monkeypatch.setenv('CODESNAP_HOME', str(tmp_path))
    manager = session.SessionManager()
    manager._proc = SimpleNamespace(pid=os.getpid(), poll=lambda: None)
    return manager


def test_a_running_capture_picks_up_a_new_area_on_the_next_frame(manager, monkeypatch):
    import hotkey_capture
    monkeypatch.setattr(hotkey_capture, 'CAPTURES_ROOT', session.PROJECT/'captures')
    app = hotkey_capture.App.__new__(hotkey_capture.App)
    app.region, app.display = None, 1
    assert app._refresh_capture_area() is False
    manager.configure('0.1,0.2,0.7,0.5', '1')
    assert app._refresh_capture_area() is True and app.region == (0.1, 0.2, 0.7, 0.5)
    assert app._refresh_capture_area() is False
    manager.configure('0.3,0.2,0.5,0.5', '1')
    assert app._refresh_capture_area() is True and app.region == (0.3, 0.2, 0.5, 0.5)


def test_settings_endpoint_says_the_change_applies_now_while_capturing(manager, monkeypatch):
    from fastapi.testclient import TestClient
    from webapp import server
    monkeypatch.setattr(server, '_session', manager)
    res = TestClient(server.app).post('/api/session/settings', json={'region': '0.1,0.1,0.5,0.5', 'display': '1'})
    assert res.json()['applies'] == 'now'
    manager._proc = None
    res = TestClient(server.app).post('/api/session/settings', json={'region': '0.1,0.1,0.5,0.5', 'display': '1'})
    assert res.json()['applies'] == 'next_capture'


def test_cut_off_corrected_source_is_never_used():
    from core import analysis
    seen = {}

    class Client:
        messages = SimpleNamespace(create=lambda **kw: seen.update(kw) or SimpleNamespace(
            content=[SimpleNamespace(text="partial")], stop_reason="max_tokens"))

    with pytest.raises(ValueError):
        analysis.fix_source(Client, "x" * 30000, "COBOL", "err")
    assert seen["max_tokens"] >= 15000


def test_json_reader_allows_dense_frames(tmp_path):
    from PIL import Image
    from core import analysis
    path = tmp_path / "f.png"
    Image.new("RGB", (40, 40), "white").save(path)
    seen = {}

    class Client:
        messages = SimpleNamespace(create=lambda **kw: seen.update(kw) or SimpleNamespace(
            content=[SimpleNamespace(text="{}")], stop_reason="max_tokens"))

    with pytest.raises(ValueError):
        analysis.extract_json(Client, path)
    assert seen["max_tokens"] == 8192
