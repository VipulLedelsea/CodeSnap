import json
import hashlib
import re
from pathlib import Path

from core.usage import cost as usage_cost

from .extract import PROMPT_VERSION, extract_structure
from .kinds import ENTITY_KINDS, RELATION_KINDS

STRUCTURED_TYPES = {"code", "sql", "db_schema", "config", "api", "job", "web", "ui_screen"}
TYPE_BY_EXTENSION = {"bms": "code", "jcl": "job", "sql": "sql", "ddl": "db_schema", "config": "config",
                     "html": "web", "htm": "web", "aspx": "web", "ascx": "web", "asp": "web", "jsp": "web",
                     "jspx": "web", "xhtml": "web", "cshtml": "web", "wsdl": "api", "sps": "job",
                     "xml": "config", "properties": "config", "ini": "config", "cfg": "config", "conf": "config",
                     "json": "config", "yaml": "config", "yml": "config", "env": "config"}


def artifact_type_for(report: dict, is_code: bool) -> str:
    if is_code and (report.get("extension") or "").lower().lstrip(".") == "bms":
        return "code"
    if report.get("artifact_type"):
        return report["artifact_type"]
    if not is_code:
        return "other"
    extension=(report.get("extension") or "").lower().lstrip(".")
    extra={'vue':'web','jsx':'web','tsx':'web','razor':'web','hbs':'web','mustache':'web','ftl':'web','vm':'web',
           'xsl':'config','xslt':'config','caml':'config','bpel':'api','rdl':'config','rdlc':'config','dtsx':'config','mxml':'web'}
    return TYPE_BY_EXTENSION.get(extension,extra.get(extension,'code'))


def artifact_name(report: dict, fallback: str = "capture") -> str:
    stem = (report.get("code_name") or report.get("out_name") or fallback).strip()
    stem = re.sub(r"^(Code|Report)_", "", stem) or fallback
    ext = (report.get("extension") or "").strip().lstrip(".")
    return f"{stem}.{ext}" if ext and not stem.endswith(f".{ext}") else stem


def validation_from_errors(errors: str) -> tuple:
    text = (errors or "").strip()
    if text.startswith("Not verified"):
        return None, text  # no compiler for this language: unverified, not failed
    return text in ("", "None"), "" if text in ("", "None") else text


def _kind(kind, allowed, default):
    return kind if kind in allowed else default


def apply_structure(store, artifact_id: int, structure: dict, filename: str, total_lines: int | None = None) -> dict:
    file_id = store.upsert_entity("file", filename, artifact_id=artifact_id, line_start=1, line_end=total_lines,
                                  attrs=structure.get("file_attrs") or None)
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
                           target_kind=target_kind, attrs=item.get("attrs") or None)
        relations += 1
    return {"entities": created, "relations": relations}


def ingest_artifact(store, client, artifact_id: int) -> dict:
    artifact = store.artifact(artifact_id)
    if artifact is None:
        raise KeyError(artifact_id)
    from core.technology_support import resolve
    support=resolve(artifact['name'],artifact.get('language') or '')
    if artifact["artifact_type"] not in STRUCTURED_TYPES or not (artifact["transcription"] or "").strip():
        return {"entities": 0, "relations": 0, "skipped": True}
    store.clear_artifact(artifact_id)
    code = artifact["transcription"]
    parsed = _parse_deterministic(code, artifact, prefer_llm=client is not None)
    if parsed is None and client is not None:
        try:
            structure = extract_structure(client, code, filename=artifact["name"], language=artifact["language"])
        except Exception as exc:
            store.log_run("structure", artifact_id=artifact_id, prompt_version=PROMPT_VERSION, ok=False,
                          error=f"{type(exc).__name__}: {exc}")
            parsed = _parse_deterministic(code, artifact)
            if parsed is None:
                store.set_status(artifact_id, "failed")
                raise
            parsed["fallback"] = f"{type(exc).__name__}"
        else:
            return _apply_llm(store, artifact_id, artifact, code, structure)
    if parsed is not None:
        from core.technology_support import coverage
        parsed['structure'].setdefault('file_attrs',{})['analysis_coverage']=coverage(
            artifact['name'],artifact.get('language') or '',parsed['parser'],
            limited=bool(support and support['model_enrichment']))
        counts = apply_structure(store, artifact_id, parsed["structure"], artifact["name"], len(code.splitlines()))
        store.log_run("structure", artifact_id=artifact_id, model=parsed["parser"], prompt_version=parsed["parser"],
                      input_tokens=0, output_tokens=0, ms=parsed["ms"])
        store.set_status(artifact_id, "structured")
        _relink(store)
        return {**counts, "parser": parsed["parser"]}
    try:
        if client is None:
            raise ValueError("This visible source format requires model analysis; no analysis client is available.")
        structure = extract_structure(client, code, filename=artifact["name"], language=artifact["language"])
    except Exception as exc:
        store.log_run("structure", artifact_id=artifact_id, prompt_version=PROMPT_VERSION, ok=False,
                      error=f"{type(exc).__name__}: {exc}")
        store.set_status(artifact_id, "failed")
        raise
    return _apply_llm(store, artifact_id, artifact, code, structure)


def _apply_llm(store, artifact_id, artifact, code, structure):
    for call in structure["calls"]:
        store.log_run("structure", artifact_id=artifact_id, model=call["model"], prompt_version=PROMPT_VERSION,
                      input_tokens=call["input_tokens"], output_tokens=call["output_tokens"], ms=call["ms"],
                      cost=usage_cost(call["model"], call["input_tokens"], call["output_tokens"]),
                      ok=call.get("stop_reason") != "max_tokens",
                      error="output truncated (max_tokens)" if call.get("stop_reason") == "max_tokens" else None)
    if any(call.get('stop_reason')=='max_tokens' for call in structure['calls']):
        store.set_status(artifact_id,'failed')
        raise ValueError('Source analysis was truncated; it must be completed before treating the file as analyzed.')
    if not structure.get("file_attrs"):
        try:
            from core import langpacks
            det = langpacks.parse(code, artifact["name"], artifact.get("language") or "")
            if det and det.get("file_attrs"):
                structure["file_attrs"] = det["file_attrs"]
        except Exception:
            pass
    from core.technology_support import coverage
    structure.setdefault('file_attrs',{})['analysis_coverage']=coverage(
        artifact['name'],artifact.get('language') or '',PROMPT_VERSION)
    counts = apply_structure(store, artifact_id, structure, artifact["name"], len(code.splitlines()))
    store.set_status(artifact_id, "structured")
    _relink(store)
    return counts


def _relink(store):
    from .linker import link_program
    try:
        return link_program(store)
    except Exception:
        return None


def _parse_deterministic(code: str, artifact: dict, prefer_llm: bool = False):
    import time
    from core.cobol.parser import PARSER_VERSION as COBOL_VERSION, parse as parse_cobol_family
    from core.extractors import PARSER_VERSION as EXTRACTORS_VERSION, parse_artifact
    from core.langs.structure import PARSER_VERSION as TS_VERSION, parse_source
    began = time.monotonic()
    from core.technology_support import resolve
    support=resolve(artifact['name'],artifact.get('language') or '')
    # A generic config inventory cannot stand in for a visual tool's business
    # rules/data flow. Let model analysis read the visible schema/source.
    if prefer_llm and support and support['model_enrichment']:
        return None
    atype = artifact.get("artifact_type") or ""
    from core import langpacks
    extractors = (EXTRACTORS_VERSION, lambda c, n, l: parse_artifact(c, n, l, atype))
    cobol = (COBOL_VERSION, lambda c, n, l: langpacks.enrich_cobol(c, parse_cobol_family(c, n, l)))
    packs = (langpacks.PARSER_VERSION, lambda c, n, l: langpacks.parse(c, n, l, skip_llm_first=prefer_llm))
    chain = [cobol, (TS_VERSION, parse_source), packs, extractors]
    if code.lstrip().startswith("{\n  \"codesnap_ui_screen\""):
        chain = [extractors] + chain[:3]
    elif atype in ("sql", "db_schema", "config", "api", "web", "ui_screen"):
        try:
            first = langpacks.claims(code, artifact["name"], artifact.get("language") or "", atype)
        except Exception:
            first = False
        chain = ([packs, extractors] if first else [extractors, packs]) + chain[:2]
    for version, fn in chain:
        try:
            structure = fn(code, artifact["name"], artifact.get("language") or "")
        except Exception:
            structure = None
        if structure is not None:
            return {"structure": structure, "parser": version, "ms": int((time.monotonic() - began) * 1000)}
    return None


def ingest_capture(store, client, images, report: dict, *, session_id: int | None = None,
                   name: str | None = None) -> int:
    evidence_ids = [store.add_evidence(Path(p), session_id=session_id) for p in images]
    is_code = report.get("is_code", True) and bool((report.get("code") or "").strip())
    artifact_id = store.add_artifact(
        name or artifact_name(report),
        artifact_type_for(report, is_code),
        report.get("language", ""),
        report.get("code", ""),
        evidence_ids=evidence_ids,
    )
    if report.get("verification"):
        store.set_verification(artifact_id, report["verification"])
    if is_code:
        ok, errors = validation_from_errors(report.get("errors", ""))
        store.set_validation(artifact_id, report.get("validation_tool", "compiler"), ok, errors)
        if client is not None:
            try:
                ingest_artifact(store, client, artifact_id)
            except Exception:
                pass
    return artifact_id


def _finish(store, client, artifact_id, report, is_code):
    if (report or {}).get("verification") or store.verification(artifact_id):
        store.set_verification(artifact_id, (report or {}).get("verification"))
    if is_code:
        ok, errors = validation_from_errors(report.get("errors", ""))
        store.set_validation(artifact_id, report.get("validation_tool", "compiler"), ok, errors)
        try:
            ingest_artifact(store, client, artifact_id)
        except Exception:
            pass


def new_version_from(store, client, source_id: int, target_name: str, report: dict | None = None) -> int:
    """Make capture `source_id` the next version of file `target_name` (the old version is kept as history)."""
    src = store.artifact(source_id)
    ev = [e["id"] for e in store.artifact_evidence(source_id)]
    report = report or {"code": src["transcription"], "language": src["language"], "artifact_type": src["artifact_type"],
                        "errors": src["validation_errors"] or ("None" if src["validation_ok"] else ""),
                        "validation_tool": src["validation_tool"] or "compiler"}
    code = report.get("code") or ""
    is_code = bool(code.strip())
    # Publish together; provider-backed parsing happens after the write transaction.
    with store.transaction():
        pending = store.pending_captures().get(source_id) or {}
        if pending.get('capture_incomplete'):
            raise ValueError('Screen capture was interrupted. Recapture or add the missing screenshots before replacing a file.')
        expected = pending.get('recapture_target_id')
        current = store.current_artifact(target_name)
        if expected is not None and (not current or current['id'] != expected):
            raise ValueError('The recapture target changed during analysis. Results were saved; choose the current file before retrying.')
        expected_hash = pending.get('recapture_target_hash')
        if expected_hash and hashlib.sha256((current['transcription'] or '').encode()).hexdigest() != expected_hash:
            raise ValueError('The recapture target text changed during analysis. No replacement was made.')
        if not store.artifact(source_id):
            raise ValueError('This capture was removed during analysis.')
        if pending.get('recapture_of'):
            from core.deepdive import note_recapture
            note_recapture(store, target_name)
        new_id = store.add_artifact(target_name, artifact_type_for(report, is_code), report.get("language", ""), code,
                                    evidence_ids=ev)
        store.repoint_runs(source_id, new_id)
        store.delete_artifact(source_id)
    _finish(store, client, new_id, report, is_code)
    return new_id


def complete_capture(store, client, artifact_id: int, report: dict | None) -> int:
    """Fill a saved capture (see ProgramStore.add_pending_capture) with its analysis. Keeps the name the user gave it;
    otherwise names it from the content without ever replacing another file. A capture started as a recapture becomes
    the next version of that file."""
    info = store.pending_captures().get(artifact_id) or {}
    art = store.artifact(artifact_id)
    if art is None:
        return artifact_id
    if info.get('capture_incomplete'):
        raise ValueError('Screen capture was interrupted. Recapture or add the missing screenshots before completing analysis.')
    code = (report or {}).get("code") or ""
    is_code = bool((report or {}).get("is_code", True)) and bool(code.strip())
    if not report or not code.strip():
        store.update_pending(artifact_id, error="No text could be read from this capture.", claim=None)
        store.set_status(artifact_id, "failed")
        return artifact_id
    target = info.get("recapture_of")
    expected = info.get('recapture_target_id')
    if target and expected is not None and (store.current_artifact(target) or {}).get('id') != expected:
        raise ValueError('The recapture target changed during analysis. No replacement was made.')
    if target and (store.current_artifact(target) or {}).get("id") not in (None, artifact_id):
        return new_version_from(store, client, artifact_id, target, report)
    if art["name"] == info.get("provisional_name"):
        store.rename_artifact(artifact_id, store.unique_name(artifact_name(report), exclude_id=artifact_id))
    store.fill_artifact(artifact_id, artifact_type=artifact_type_for(report, is_code),
                        language=report.get("language", ""), transcription=code)
    store.clear_pending(artifact_id)
    _finish(store, client, artifact_id, report, is_code)
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
