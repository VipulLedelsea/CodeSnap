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
