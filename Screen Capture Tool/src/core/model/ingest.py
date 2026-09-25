import json
import re
from pathlib import Path

from .extract import PROMPT_VERSION, extract_structure
from .kinds import ENTITY_KINDS, RELATION_KINDS

STRUCTURED_TYPES = {"code", "sql", "db_schema", "config", "api", "job", "web"}


def artifact_name(report: dict, fallback: str = "capture") -> str:
    stem = (report.get("code_name") or report.get("out_name") or fallback).strip()
    stem = re.sub(r"^(Code|Report)_", "", stem) or fallback
    ext = (report.get("extension") or "").strip().lstrip(".")
    return f"{stem}.{ext}" if ext and not stem.endswith(f".{ext}") else stem


def validation_from_errors(errors: str) -> tuple:
    text = (errors or "").strip()
    return text in ("", "None"), "" if text in ("", "None") else text


def _kind(kind, allowed, default):
    return kind if kind in allowed else default


def apply_structure(store, artifact_id: int, structure: dict, filename: str, total_lines: int | None = None) -> dict:
    file_id = store.upsert_entity("file", filename, artifact_id=artifact_id, line_start=1, line_end=total_lines)
    local = {}
    pending = [e for e in structure.get("entities", []) if str(e.get("name") or "").strip()]
    created = 0
    while pending:
        progress = False
        waiting = []
        for item in pending:
            parent_name = (item.get("parent") or "").strip()
            if parent_name and parent_name not in local and any(
                    (p.get("name") or "").strip() == parent_name for p in pending if p is not item):
                waiting.append(item)
                continue
            parent_id = local.get(parent_name) if parent_name else None
            kind = _kind(item.get("kind"), ENTITY_KINDS, "unknown")
            name = item["name"].strip()
            try:
                entity_id = store.upsert_entity(
                    kind, name, parent_id=parent_id, attrs=item.get("attrs") or {}, artifact_id=artifact_id,
                    line_start=item.get("line_start"), line_end=item.get("line_end"))
            except Exception:
                entity_id = store.upsert_entity(
                    kind, name, parent_id=parent_id, artifact_id=artifact_id,
                    line_start=item.get("line_start"), line_end=item.get("line_end"))
            local.setdefault(name, entity_id)
            if parent_name:
                local.setdefault(f"{parent_name}.{name}", entity_id)
            else:
                store.add_relation("contains", file_id, entity_id, artifact_id=artifact_id)
            created += 1
            progress = True
        if not progress:
            for item in waiting:
                item["parent"] = None
        pending = waiting

    relations = 0
    for item in structure.get("relations", []):
        source = str(item.get("source") or "").strip()
        target = str(item.get("target") or "").strip()
        if not source or not target:
            continue
        kind = _kind(item.get("kind"), RELATION_KINDS, "depends_on")
        target_kind = item.get("target_kind") if item.get("target_kind") in ENTITY_KINDS else None
        from_id = local.get(source) or local.get(source.split(".")[-1]) or file_id
        to_id = local.get(target) or target
        store.add_relation(kind, from_id, to_id, artifact_id=artifact_id, line=item.get("line"),
                           target_kind=target_kind)
        relations += 1
    return {"entities": created, "relations": relations}


def ingest_artifact(store, client, artifact_id: int) -> dict:
    artifact = store.artifact(artifact_id)
    if artifact is None:
        raise KeyError(artifact_id)
    if artifact["artifact_type"] not in STRUCTURED_TYPES or not (artifact["transcription"] or "").strip():
        return {"entities": 0, "relations": 0, "skipped": True}
    store.clear_artifact(artifact_id)
    code = artifact["transcription"]
    try:
        structure = extract_structure(client, code, filename=artifact["name"], language=artifact["language"])
    except Exception as exc:
        store.log_run("structure", artifact_id=artifact_id, prompt_version=PROMPT_VERSION, ok=False,
                      error=f"{type(exc).__name__}: {exc}")
        store.set_status(artifact_id, "failed")
        raise
    for call in structure["calls"]:
        store.log_run("structure", artifact_id=artifact_id, model=call["model"], prompt_version=PROMPT_VERSION,
                      input_tokens=call["input_tokens"], output_tokens=call["output_tokens"], ms=call["ms"],
                      ok=call.get("stop_reason") != "max_tokens",
                      error="output truncated (max_tokens)" if call.get("stop_reason") == "max_tokens" else None)
    counts = apply_structure(store, artifact_id, structure, artifact["name"], len(code.splitlines()))
    store.set_status(artifact_id, "structured")
    return counts


def ingest_capture(store, client, images, report: dict, *, session_id: int | None = None,
                   name: str | None = None) -> int:
    evidence_ids = [store.add_evidence(Path(p), session_id=session_id) for p in images]
    is_code = report.get("is_code", True) and bool((report.get("code") or "").strip())
    artifact_id = store.add_artifact(
        name or artifact_name(report),
        report.get("artifact_type") or ("code" if is_code else "other"),
        report.get("language", ""),
        report.get("code", ""),
        evidence_ids=evidence_ids,
    )
    if is_code:
        ok, errors = validation_from_errors(report.get("errors", ""))
        store.set_validation(artifact_id, report.get("validation_tool", "compiler"), ok, errors)
        if client is not None:
            try:
                ingest_artifact(store, client, artifact_id)
            except Exception:
                pass
    return artifact_id


def import_reports(store, report_dirs, client=None) -> list:
    imported = []
    seen = {a["name"] for a in store.artifacts()}
    for directory in report_dirs:
        directory = Path(directory)
        if not directory.exists():
            continue
        for bundle in sorted(directory.glob("*.json")):
            try:
                meta = json.loads(bundle.read_text())
            except (OSError, ValueError):
                continue
            code = meta.get("code") or ""
            if not code.strip() or str(meta.get("language", "")).lower() == "project":
                continue
            name = meta.get("code_file") or artifact_name({"code_name": bundle.stem, **meta})
            name = re.sub(r"^Code_", "", name)
            if name in seen:
                continue
            report = {**meta, "code": code}
            artifact_id = ingest_capture(store, client, [], report, name=name)
            imported.append({"artifact_id": artifact_id, "name": name, "bundle": bundle.name})
            seen.add(name)
    return imported
