import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from webapp import session


@pytest.fixture
def manager(tmp_path, monkeypatch):
    monkeypatch.setattr(session, 'PROJECT', tmp_path)
    manager = session.SessionManager()
    manager._proc = SimpleNamespace(pid=os.getpid(), poll=lambda: None)
    return manager


def test_area_change_updates_idle_worker_without_relaunch(manager, monkeypatch):
    monkeypatch.setattr(session.subprocess, 'Popen', lambda *a, **k: pytest.fail('Must preserve the existing worker'))
    assert manager.start(region='0.2,0.1,0.5,0.6', display='2') is False
    saved = json.loads((session.PROJECT/'captures/.capture_settings.json').read_text())
    assert saved == {'pid': os.getpid(), 'region': [0.2,0.1,0.5,0.6], 'display': 2}


def test_worker_loads_latest_area_and_screen_at_next_capture(manager, monkeypatch):
    import hotkey_capture
    monkeypatch.setattr(hotkey_capture, 'CAPTURES_ROOT', session.PROJECT/'captures')
    app = hotkey_capture.App.__new__(hotkey_capture.App)
    app.region, app.display = None, 1
    manager.configure('0.1,0.2,0.7,0.5', '2')
    app._load_capture_settings()
    assert app.region == (0.1,0.2,0.7,0.5) and app.display == 2
    manager.configure(None, '1')
    app._load_capture_settings()
    assert app.region is None and app.display == 1


def test_settings_for_other_worker_do_not_change_capture(manager, monkeypatch):
    import hotkey_capture
    monkeypatch.setattr(hotkey_capture, 'CAPTURES_ROOT', session.PROJECT/'captures')
    manager._proc.pid = os.getpid()+1000
    manager.configure('0,0,0.5,0.5', '2')
    app = hotkey_capture.App.__new__(hotkey_capture.App)
    app.region, app.display = None, 1
    app._load_capture_settings()
    assert app.region is None and app.display == 1


@pytest.mark.parametrize('region', ['0,0,0,1', '0.9,0,0.5,1', '-0.1,0,1,1', 'NaN,0,1,1', '0,0,1'])
def test_invalid_selection_cannot_replace_saved_area(manager, region):
    manager.configure('0,0,0.5,0.5', '1')
    path=session.PROJECT/'captures/.capture_settings.json'
    old=path.read_text()
    with pytest.raises(ValueError):manager.configure(region, '1')
    assert path.read_text()==old


def test_settings_endpoint_updates_existing_worker(manager, monkeypatch):
    from webapp import server
    monkeypatch.setattr(server, '_session', manager)
    client=TestClient(server.app)
    answer=client.post('/api/session/settings',json={'region':'0.2,0.1,0.5,0.6','display':'2'})
    assert answer.status_code==200
    assert answer.json()['applies']=='now'
    assert manager._settings['display']==2
    assert client.post('/api/session/settings',json={'region':'0,0,2,2','display':'2'}).status_code==400
