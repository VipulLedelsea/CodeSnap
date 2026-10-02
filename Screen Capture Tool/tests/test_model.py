import json
import sqlite3
import threading

import pytest

from core.model import ProgramStore, SCHEMA_VERSION, entity_key
from core.model.schema import current_version


@pytest.fixture
def root(tmp_path):
    return tmp_path / "programs"


@pytest.fixture
def store(root):
    s = ProgramStore.create("MDE Aid Calc", "fixture", root=root)
    yield s
    s.close()


def png_bytes(seed: int) -> bytes:
    return b"\x89PNG\r\n\x1a\n" + bytes([seed]) * 64


def build_fixture(s: ProgramStore, files):
    session = s.add_session()
    ids = {}
    for name, (atype, lang, entities, relations) in files.items():
        ev = s.add_evidence(png_bytes(len(ids) + 1), session_id=session)
        aid = s.add_artifact(name, atype, lang, f"-- {name} --", evidence_ids=[ev])
        ids[name] = aid
        for kind, ename, parent, lines in entities:
            parent_id = s.entity_by_key(parent)["id"] if parent else None
            s.upsert_entity(kind, ename, parent_id=parent_id, artifact_id=aid, line_start=lines[0], line_end=lines[1])
        for kind, src, dst, hint in relations:
            s.add_relation(kind, src, dst, artifact_id=aid, target_kind=hint)
        s.set_status(aid, "structured")
    return ids


SESSION_ONE = {
    "main.py": ("code", "python", [("module", "main", None, (1, 20)), ("function", "run", "module:main", (3, 18))],
                [("calls", "function:main.run", "function:Billing.calculate", None),
                 ("displays", "function:main.run", "PAYSCRN", "screen")]),
    "billing.py": ("code", "python", [("class", "Billing", None, (1, 40)),
                                      ("function", "calculate", "class:Billing", (5, 30))],
                   [("reads", "function:Billing.calculate", "PAYMENTS", "table"),
                    ("calls", "function:Billing.calculate", "taxlib.rate", "function")]),
    "schema.sql": ("sql", "sql", [("table", "PAYMENTS", None, (1, 12)), ("column", "AMOUNT", "table:PAYMENTS", (3, 3))],
                   []),
}

SESSION_TWO = {
    "payscrn.bms": ("ui_screen", "bms", [("screen", "PAYSCRN", None, (1, 50))], []),
    "report.py": ("code", "python", [("function", "summary", None, (1, 10))],
                  [("reads", "function:summary", "table:PAYMENTS", None)]),
}


def test_create_open_list(root):
    s = ProgramStore.create("MDE Aid Calc", root=root)
    slug = s.info["slug"]
    s.close()
    again = ProgramStore.create("MDE Aid Calc", root=root)
    assert again.info["slug"] == f"{slug}-2"
    again.close()
    names = [p["slug"] for p in ProgramStore.list(root=root)]
    assert names == [slug, f"{slug}-2"]
    with ProgramStore.open(slug, root=root) as reopened:
        assert reopened.info["name"] == "MDE Aid Calc"
    with pytest.raises(FileNotFoundError):
        ProgramStore.open("nope", root=root)


def test_schema_version_and_idempotent_migrate(store):
    assert current_version(store._db) == SCHEMA_VERSION
    reopened = ProgramStore(store.path)
    assert current_version(reopened._db) == SCHEMA_VERSION
    reopened.close()


def test_newer_schema_refused(store):
    store._db.execute("UPDATE meta SET value = '999' WHERE key = 'schema_version'")
    with pytest.raises(RuntimeError):
        ProgramStore(store.path)


def test_evidence_dedup_and_files(store, tmp_path):
    a = store.add_evidence(png_bytes(1))
    b = store.add_evidence(png_bytes(1))
    c = store.add_evidence(png_bytes(2))
    assert a == b != c
    src = tmp_path / "shot.png"
    src.write_bytes(png_bytes(3))
    d = store.add_evidence(src)
    assert (store.evidence_dir / store.evidence(d)["path"]).exists()
    assert len(list(store.evidence_dir.iterdir())) == 3


def test_entity_keys_and_merge(store):
    cls = store.upsert_entity("class", "Billing", attrs={"bases": ["Base"]})
    fn = store.upsert_entity("function", "calculate", parent_id=cls, attrs={"params": ["x"]})
    assert store.entity(fn)["key"] == entity_key("function", "calculate", "class:Billing") == "function:Billing.calculate"
    again = store.upsert_entity("class", "Billing", attrs={"stereotype": "service"})
    assert again == cls
    assert store.entity(cls)["attrs"] == {"bases": ["Base"], "stereotype": "service"}


def test_invalid_kinds_rejected(store):
    with pytest.raises(ValueError):
        store.upsert_entity("widget", "x")
    with pytest.raises(ValueError):
        store.add_relation("teleports", "class:A", "class:B")
    with pytest.raises(ValueError):
        store.add_artifact("x", artifact_type="spreadsheet")


def test_attrs_validated(store):
    eid = store.upsert_entity("column", "AMOUNT", attrs={"nullable": "false", "extra": 1})
    assert store.entity(eid)["attrs"] == {"nullable": False, "extra": 1}
    with pytest.raises(Exception):
        store.upsert_entity("field", "F", attrs={"level": "not-a-number"})


def test_placeholder_then_upgrade(store):
    aid = store.add_artifact("a.py")
    store.upsert_entity("function", "caller", artifact_id=aid)
    store.add_relation("calls", "function:caller", "helper", artifact_id=aid, target_kind="function")
    missing = store.coverage()["missing"]
    assert [m["name"] for m in missing] == ["helper"]
    assert missing[0]["referenced_by"][0]["artifact"] == "a.py"
    bid = store.add_artifact("b.py")
    hid = store.upsert_entity("function", "helper", artifact_id=bid, line_start=1, line_end=4)
    helper = store.entity(hid)
    assert helper["origin"] == "extracted" and helper["artifact_id"] == bid and helper["line_start"] == 1
    assert store.coverage()["missing"] == []
    assert len(store.relations(kind="calls", to_id=hid)) == 1


def test_resolve_by_name(store):
    t = store.upsert_entity("table", "PAYMENTS")
    assert store.resolve("payments") == t
    assert store.resolve("PAYMENTS", "table") == t
    assert store.entity(store.resolve("GHOST"))["origin"] == "placeholder"
    assert store.resolve("OTHER", create=False) is None


def test_relation_dedup(store):
    aid = store.add_artifact("a.py")
    r1 = store.add_relation("calls", "function:a", "function:b", artifact_id=aid)
    r2 = store.add_relation("calls", "function:a", "function:b", artifact_id=aid)
    assert r1 == r2
    assert len(store.relations()) == 1


def test_versioning_supersedes_and_reextracts(store):
    v1 = store.add_artifact("billing.py", transcription="v1")
    store.upsert_entity("class", "Billing", artifact_id=v1)
    store.upsert_entity("function", "old_fn", artifact_id=v1)
    other = store.add_artifact("main.py")
    store.upsert_entity("function", "main", artifact_id=other)
    store.add_relation("uses", "function:main", "class:Billing", artifact_id=other)

    v2 = store.add_artifact("billing.py", transcription="v2")
    assert store.artifact(v1)["status"] == "superseded" and not store.artifact(v1)["is_current"]
    assert store.artifact(v2)["version"] == 2 and store.artifact(v2)["supersedes_id"] == v1
    assert store.entity_by_key("function:old_fn") is None
    assert store.entity_by_key("class:Billing")["origin"] == "placeholder"
    store.upsert_entity("class", "Billing", artifact_id=v2)
    assert store.entity_by_key("class:Billing")["origin"] == "extracted"
    assert [a["name"] for a in store.artifacts()] == ["billing.py", "main.py"]
    assert len(store.artifacts(current_only=False)) == 3
    assert (store.sources_dir / store.artifact(v1)["source_path"]).read_text() == "v1"
    assert (store.sources_dir / store.artifact(v2)["source_path"]).read_text() == "v2"


def test_clear_keeps_multi_source_and_corrected(store):
    a = store.add_artifact("a.py")
    b = store.add_artifact("b.py")
    shared = store.upsert_entity("class", "Shared", artifact_id=a, line_start=1)
    store.upsert_entity("class", "Shared", artifact_id=b, line_start=9)
    fixed = store.upsert_entity("class", "Fixed", artifact_id=a, origin="corrected")
    store.clear_artifact(a)
    assert store.entity(shared)["artifact_id"] == b and store.entity(shared)["line_start"] == 9
    assert store.entity(fixed)["origin"] == "corrected"


def test_corrected_entities_not_overwritten(store):
    eid = store.upsert_entity("class", "Pay", attrs={"stereotype": "entity"}, origin="corrected")
    store.upsert_entity("class", "Pay", attrs={"stereotype": "service"})
    assert store.entity(eid)["attrs"] == {"stereotype": "entity"}


def test_evidence_trace(store):
    ev1, ev2 = store.add_evidence(png_bytes(1)), store.add_evidence(png_bytes(2))
    aid = store.add_artifact("a.py", evidence_ids=[ev1, ev2])
    eid = store.upsert_entity("function", "f", artifact_id=aid)
    ev3 = store.add_evidence(png_bytes(3))
    store.link_evidence("entity", eid, ev3, region="10,10,200,80")
    ids = [e["id"] for e in store.evidence_for("entity", eid)]
    assert ids == [ev3, ev1, ev2]
    assert [e["id"] for e in store.evidence_for("artifact", aid)] == [ev1, ev2]


def test_validation_and_status(store):
    aid = store.add_artifact("a.c", language="c")
    store.set_validation(aid, "gcc", False, "a.c:3: error")
    art = store.artifact(aid)
    assert art["status"] == "validated" and art["validation_ok"] == 0 and "error" in art["validation_errors"]
    with pytest.raises(ValueError):
        store.set_status(aid, "exploded")


def test_findings_corrections_runs(store):
    store.add_finding("security", "high", "Hardcoded password", target_type="entity", target_id=1, evidence=[1])
    store.add_correction("entity", 1, "rename", {"name": "X"}, note="wrong name")
    store.log_run("extract", model="m", input_tokens=100, output_tokens=20, cost=0.01, ms=900)
    store.log_run("extract", ok=False, error="timeout")
    assert store.findings("security")[0]["evidence"] == [1]
    assert store.corrections()[0]["payload"] == {"name": "X"}
    usage = store.usage()
    assert usage["calls"] == 2 and usage["input_tokens"] == 100 and usage["failures"] == 1


def test_concurrent_writes(store):
    aid = store.add_artifact("big.py")

    def worker(n):
        for i in range(25):
            store.upsert_entity("function", f"f{n}_{i}", artifact_id=aid)
            store.add_relation("calls", f"function:f{n}_{i}", "function:shared", artifact_id=aid)

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(store.entities(kind="function")) == 101
    assert len(store.relations()) == 100


def test_fixture_program_two_sessions(root):
    s = ProgramStore.create("MDE Aid Calc", root=root)
    slug = s.info["slug"]
    build_fixture(s, SESSION_ONE)
    cov = s.coverage()
    assert {m["name"] for m in cov["missing"]} == {"PAYSCRN", "taxlib.rate"}
    s.close()

    s = ProgramStore.open(slug, root=root)
    build_fixture(s, SESSION_TWO)
    cov = s.coverage()
    assert cov["files"] == 5 and cov["files_by_status"] == {"structured": 5}
    assert [m["name"] for m in cov["missing"]] == ["taxlib.rate"]
    assert cov["missing"][0]["referenced_by"][0]["name"] == "calculate"
    assert cov["entities_by_kind"] == {"class": 1, "column": 1, "function": 3, "module": 1, "screen": 1, "table": 1}
    payments = s.entity_by_key("table:PAYMENTS")["id"]
    readers = {e["name"] for e in s.neighbors(payments, direction="in", kind="reads")}
    assert readers == {"calculate", "summary"}
    assert s.entity(s.entity_by_key("screen:PAYSCRN")["id"])["origin"] == "extracted"
    calc = s.entity_by_key("function:Billing.calculate")
    assert s.entity_sources(calc["id"])[0]["artifact_name"] == "billing.py"
    assert len(s.evidence_for("entity", calc["id"])) == 1
    s.close()

    s = ProgramStore.open(slug, root=root)
    data = s.export()
    on_disk = json.loads((s.exports_dir / "program.json").read_text())
    assert on_disk["program"]["slug"] == slug
    assert len(data["entities"]) == 9 and len(data["relations"]) == 5
    assert all(a["evidence"] for a in data["artifacts"])
    graph = s.graph()
    assert len(graph["nodes"]) == 9 and len(graph["edges"]) == 5
    s.close()


def test_db_is_plain_sqlite(store):
    store.upsert_entity("class", "A")
    con = sqlite3.connect(store.path / "program.db")
    assert con.execute("SELECT name FROM entity").fetchone()[0] == "A"
    con.close()
