"""The diagrams and the model behind them: one table is one table whatever its letter case, a standard-library module or a shell command is not a
system, a host named in a URL is, and a Python file is Python."""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))
sys.path.insert(0, str(HERE))

from core.model import ProgramStore  # noqa: E402
from core.model.ingest import apply_structure  # noqa: E402
from core.model.runtime_names import is_runtime  # noqa: E402


def _store(tmp_path, monkeypatch):
    monkeypatch.setenv("CODESNAP_PROGRAMS", str(tmp_path / "p"))
    return ProgramStore.create("Truth")


def test_a_table_named_in_two_letter_cases_is_one_table_with_its_links_kept(tmp_path, monkeypatch):
    s = _store(tmp_path, monkeypatch)
    sql = s.add_artifact("schema.sql", language="SQL", transcription="CREATE TABLE permits (id INT);\n")
    py = s.add_artifact("app.py", language="Python", transcription="db.execute('SELECT id FROM PERMITS')\n")
    apply_structure(s, sql, {"entities": [{"name": "PERMITS", "kind": "table"}], "relations": []}, "schema.sql", 1)
    apply_structure(s, py, {"entities": [], "relations": [{"source": "app.py", "target": "permits", "target_kind": "table", "kind": "reads"}]}, "app.py", 1)
    assert [e["name"] for e in s.entities("table")] == ["PERMITS"]
    assert s.relations(to_id=s.entities("table")[0]["id"])
    s.close()


def test_duplicates_already_stored_are_merged_when_the_program_is_opened(tmp_path, monkeypatch):
    s = _store(tmp_path, monkeypatch)
    a = s.add_artifact("schema.sql", language="SQL", transcription="x\n")
    t1 = s.upsert_entity("table", "PERMITS", key="table:PERMITS", artifact_id=a)
    t2 = s.upsert_entity("table", "permits", key="table:permits")
    src = s.upsert_entity("file", "app.py", artifact_id=a)
    s.add_relation("reads", src, t2)
    slug = s.info["slug"]
    s.close()
    again = ProgramStore.open(slug)
    names = [e["name"] for e in again.entities("table")]
    assert names == ["PERMITS"] and again.relations(to_id=again.entities("table")[0]["id"])
    again.close()


def test_runtime_names_are_not_systems_but_real_ones_are():
    assert is_runtime("email.message.EmailMessage", "class") and is_runtime("hashlib", "module") and is_runtime("curl", "external_system")
    assert is_runtime("sqlite3", "data_store")
    assert not is_runtime("smtp.cityhall.example", "external_system") and not is_runtime("permits.db", "data_store")
    assert not is_runtime("workflow", "module") and not is_runtime("sftp", "external_system")


def test_a_host_in_a_url_becomes_an_outside_system_but_an_xml_namespace_does_not(tmp_path, monkeypatch):
    s = _store(tmp_path, monkeypatch)
    code = 'SMS_ENDPOINT = "https://sms.example.com/v1/send"\nNS = "http://www.w3.org/2000/svg"\n'
    a = s.add_artifact("notifications.py", language="Python", transcription=code)
    apply_structure(s, a, {"entities": [], "relations": []}, "notifications.py", 2)
    assert [e["name"] for e in s.entities("external_system")] == ["sms.example.com"]
    s.close()


def test_python_files_form_one_group_with_physical_line_counts_and_no_runtime_nodes(tmp_path, monkeypatch):
    from core.diagrams import build
    s = _store(tmp_path, monkeypatch)
    code = "import os\n\n\ndef f():\n    return 1\n\n"
    a = s.add_artifact("fees.py", language="Python", transcription=code)
    apply_structure(s, a, {"entities": [{"name": "f", "kind": "function"}], "relations": [
        {"source": "fees.py", "target": "os", "target_kind": "module", "kind": "imports"}]}, "fees.py", 6)
    arch = build.architecture(s)
    text = str(arch)
    assert "Python" in text and "6 lines" in text and "Scripts & job control" not in text
    s.close()


def test_a_table_the_code_uses_but_no_schema_creates_is_drawn_as_not_created(tmp_path, monkeypatch):
    from core.diagrams import build
    s = _store(tmp_path, monkeypatch)
    sql = s.add_artifact("schema.sql", language="SQL", transcription="CREATE TABLE permits (id INT);\n")
    py = s.add_artifact("sched.py", language="Python", transcription="db.execute('SELECT slot FROM bookings')\n")
    apply_structure(s, sql, {"entities": [{"name": "permits", "kind": "table"}], "relations": []}, "schema.sql", 1)
    apply_structure(s, py, {"entities": [{"name": "bookings", "kind": "table"}], "relations": []}, "sched.py", 1)
    nodes = {n["title"]: n for n in build.data_model(s)["nodes"]}
    assert nodes["bookings"]["stereotype"] == "table · not created by the schema"
    assert nodes["permits"]["stereotype"] == "table"
    s.close()
