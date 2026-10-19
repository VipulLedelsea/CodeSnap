import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from core import paths  # noqa: E402


def test_from_source_the_data_folder_is_the_project_folder(monkeypatch):
    monkeypatch.delenv("CODESNAP_HOME", raising=False)
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    assert paths.data_root() == ROOT
    assert paths.captures_dir() == ROOT / "captures" and paths.reports_dir() == ROOT / "reports"


def test_the_bundled_app_never_writes_inside_itself(monkeypatch, tmp_path):
    monkeypatch.delenv("CODESNAP_HOME", raising=False)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    assert paths.data_root() == tmp_path / "CodeSnap"
    assert paths.captures_dir() == tmp_path / "CodeSnap" / "captures"


def test_codesnap_home_overrides_both(monkeypatch, tmp_path):
    monkeypatch.setenv("CODESNAP_HOME", str(tmp_path / "x"))
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert paths.data_root() == tmp_path / "x"


def test_no_module_builds_a_write_path_from_its_own_location():
    """A path taken from __file__ lands inside the app bundle once the app is packaged; writes go through core.paths."""
    offenders = []
    for py in (ROOT / "src").rglob("*.py"):
        text = py.read_text()
        for m in re.finditer(r"__file__[^\n]*[\"'](captures|reports)[\"']", text):
            offenders.append(f"{py.relative_to(ROOT)}: {m.group(0)[:80]}")
    assert not offenders, offenders


def test_the_spec_bundles_every_data_file_the_code_reads():
    spec = (ROOT / "packaging" / "CodeSnap.spec").read_text()
    data_files = [p for p in (ROOT / "src").rglob("*") if p.is_file() and p.suffix not in (".py", ".pyc")
                  and "__pycache__" not in p.parts and "static" not in p.parts]
    missing = [str(p.relative_to(ROOT / "src")) for p in data_files
               if p.name not in spec and p.parent.name not in spec]
    assert not missing, f"not bundled by packaging/CodeSnap.spec: {missing}"
    assert "icon='CodeSnap.icns'" in spec and (ROOT / "packaging" / "CodeSnap.icns").exists()


def test_the_spec_bundles_python_docx_as_real_folders():
    """python-docx reads its templates through docx/parts/../templates, which only resolves when docx/parts exists on disk."""
    spec = (ROOT / "packaging" / "CodeSnap.spec").read_text()
    assert "collect_data_files('docx', include_py_files=True)" in spec and "_docx_datas" in spec.split("datas=[")[1]
    assert (ROOT / "packaging" / "smoke_test.command").exists()


def test_a_fresh_install_creates_its_data_folder_on_first_use(monkeypatch, tmp_path):
    """~/CodeSnap does not exist on a clean Mac; the first thing that needs captures/ must create the whole path."""
    from fastapi.testclient import TestClient
    from webapp import server
    monkeypatch.setenv("CODESNAP_HOME", str(tmp_path / "new" / "CodeSnap"))
    reply = TestClient(server.app).post("/api/session/kind?kind=code")
    assert reply.status_code == 200
    assert (tmp_path / "new" / "CodeSnap" / "captures" / ".capture_kind").read_text() == "code"


def test_permissions_report_what_is_missing_and_only_open_known_panes(monkeypatch):
    from core import permissions
    monkeypatch.setattr(permissions, "screen_recording", lambda: False)
    monkeypatch.setattr(permissions, "accessibility", lambda: None)       # unknown is not "missing"
    monkeypatch.setattr(permissions, "input_monitoring", lambda: False)   # the hotkey cannot hear keys without it
    assert permissions.missing() == ["screen", "input"]
    opened = []
    monkeypatch.setattr(permissions.subprocess, "run", lambda argv, **k: opened.append(argv))
    monkeypatch.setattr(permissions.sys, "platform", "darwin")
    assert permissions.request("accessibility") is True and opened[-1][0] == "open"
    assert permissions.request("../../etc/passwd") is False and len(opened) == 1


def test_the_permissions_endpoints(monkeypatch):
    from fastapi.testclient import TestClient
    from core import permissions
    from webapp import server
    monkeypatch.setattr(permissions, "status", lambda: {"screen": False, "accessibility": True, "input": False})
    client = TestClient(server.app)
    assert client.get("/api/permissions").json() == {"screen": False, "accessibility": True, "input": False, "missing": ["screen", "input"]}
    assert permissions.PANES["input"].endswith("Privacy_ListenEvent")
    assert client.post("/api/permissions/open?pane=bogus").status_code == 400


def test_about_reports_the_version_the_bundle_is_built_with():
    from fastapi.testclient import TestClient
    from core.version import VERSION
    from webapp import server
    about = TestClient(server.app).get("/api/about").json()
    assert about["version"] == VERSION and about["programs"]
    spec = (ROOT / "packaging" / "CodeSnap.spec").read_text()
    assert "'CFBundleShortVersionString': VERSION" in spec and "1.0.0'" not in spec.split("info_plist")[1]


def test_the_page_loads_no_third_party_script_and_the_bundled_mermaid_is_the_checked_one():
    import base64
    import hashlib
    html = (ROOT / "src" / "webapp" / "static" / "index.html").read_text()
    assert not re.findall(r'<script[^>]+src="https?://', html), "the app page must not load a script from another site"
    lib = ROOT / "src" / "webapp" / "static" / "vendor" / "mermaid.min.js"
    want = re.search(r"sha512-[A-Za-z0-9+/=]+", (lib.parent / "NOTICE.txt").read_text()).group(0)
    assert "sha512-" + base64.b64encode(hashlib.sha512(lib.read_bytes()).digest()).decode() == want
    js = (ROOT / "src" / "webapp" / "static" / "app.js").read_text()
    assert all("integrity=" in tag for tag in re.findall(r"<script src=\"https://[^>]+>", js))   # the exported report pins its copy


def test_a_file_scrolled_to_its_top_before_capture_is_not_asked_whether_its_first_line_is_the_top(tmp_path, monkeypatch):
    """The capture proves the top by scrolling up until the picture stops changing, and records it with the session."""
    from PIL import Image
    from core.model import ProgramStore, edges
    monkeypatch.setenv("CODESNAP_PROGRAMS", str(tmp_path / "programs"))
    text = "import os\nimport sys\n\nprint(os.name)\n"
    with ProgramStore.create("Top proof") as store:
        def file_from(session_note, name):
            png = tmp_path / f"{name}.png"
            Image.new("RGB", (40, 20), (len(name) * 7, 1, 1)).save(png)
            session = store.add_session(mode="burst", note=session_note)
            evidence = store.add_evidence(png, session_id=session)
            return store.add_artifact(name, language="Python", transcription=text, evidence_ids=[evidence])
        proven = store.artifact(file_from("top_proven", "proven.py"))
        unproven = store.artifact(file_from("", "unproven.py"))
        assert edges.top_proven(store, proven) and not edges.top_proven(store, unproven)
        assert "start" not in [f["kind"] for f in edges.flags(store, proven)]
        assert "start" in [f["kind"] for f in edges.flags(store, unproven)]


def test_the_area_dialog_can_always_say_what_went_wrong():
    """The page toast sat under the dialog's overlay, so a failed save looked like nothing happening; the dialog now has its own message
    line, the disabled button looks disabled, and a margin that cannot be measured does not stop the area from being saved."""
    css = (ROOT / "src" / "webapp" / "static" / "styles.css").read_text()
    html = (ROOT / "src" / "webapp" / "static" / "index.html").read_text()
    js = (ROOT / "src" / "webapp" / "static" / "app.js").read_text()
    modal_z = int(re.search(r"\.region-modal\s*\{[^}]*z-index:(\d+)", css).group(1))
    toast_z = int(re.findall(r"\.toast\s*\{\s*z-index:(\d+)", css)[-1])
    assert toast_z > modal_z
    assert 'id="regionNote"' in html and ".btn-primary:disabled" in css
    use = js[js.index('$("regionUse").addEventListener'):]
    assert "Spacing cannot be measured" in use and "clear_spacing: true" in use          # falls back to saving the area without the margin
    assert "if (loading)" in js and "The red line is locked" in js                       # no drawing during the countdown; a click in a locked box keeps it


def test_the_unmeasurable_margin_message_says_what_to_do():
    from core import spacing
    import pytest
    from PIL import Image
    import io
    blank = io.BytesIO()
    Image.new("RGB", (400, 300), (255, 255, 255)).save(blank, format="PNG")
    with pytest.raises(ValueError) as why:
        spacing.profile(blank.getvalue(), [0.1, 0.1, 0.5, 0.5], 0.2)
    assert "line numbers" in str(why.value) and "fixed-width" in str(why.value)
