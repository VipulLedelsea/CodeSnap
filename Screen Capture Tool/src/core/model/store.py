import hashlib
import json
import shutil

from core import robust
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from .kinds import (
    ARTIFACT_STATUSES, ARTIFACT_TYPES, ENTITY_KINDS, MEMBER_KINDS, ORIGINS, RELATION_KINDS,
    check_kind, validate_attrs,
)
from .schema import SCHEMA_VERSION, migrate
from .workspace import programs_root, safe_filename, slugify, unique_dir

DB_NAME = "program.db"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _row(row) -> dict | None:
    if row is None:
        return None
    out = dict(row)
    for field in ("attrs", "payload", "evidence", "refs"):
        if field in out and isinstance(out[field], str):
            out[field] = json.loads(out[field])
    return out


def entity_key(kind: str, name: str, parent_key: str | None = None) -> str:
    base = (name or "").strip()
    if parent_key and kind in MEMBER_KINDS:
        base = f"{parent_key.split(':', 1)[1]}.{base}"
    return f"{kind}:{base}"


def _owner_alive(owner) -> bool:
    """A claim by a capture worker that has since exited (e.g. restarted for a mode switch) no longer counts."""
    import os
    try:
        os.kill(int(str(owner).split(":")[0]), 0)
        return True
    except ProcessLookupError:
        return False
    except (ValueError, PermissionError, OSError):
        return True


class ProgramStore:
    def __init__(self, path):
        self.path = Path(path)
        self.evidence_dir = self.path / "evidence"
        self.sources_dir = self.path / "sources"
        self.exports_dir = self.path / "exports"
        for d in (self.path, self.evidence_dir, self.sources_dir, self.exports_dir):
            d.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._db = sqlite3.connect(self.path / DB_NAME, check_same_thread=False, isolation_level=None)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA foreign_keys = ON")
        self._db.execute("PRAGMA journal_mode = WAL")
        self._db.execute("PRAGMA busy_timeout = 5000")
        with self._lock:
            migrate(self._db)
        self._repair_source_collisions()

    def _repair_source_collisions(self):
        """Recover old managed-path collisions from the authoritative database text."""
        import uuid
        created = []
        try:
            with self.transaction() as db:
                collisions = db.execute("SELECT source_path FROM artifact WHERE source_path IS NOT NULL "
                                        "GROUP BY source_path HAVING COUNT(*) > 1").fetchall()
                for row in collisions:
                    for artifact in db.execute("SELECT id,transcription FROM artifact WHERE source_path=?", (row[0],)).fetchall():
                        path = self.sources_dir / f"{uuid.uuid4().hex}.source"
                        path.write_text(artifact["transcription"] or "")
                        created.append(path)
                        db.execute("UPDATE artifact SET source_path=? WHERE id=?", (path.name, artifact["id"]))
        except Exception:
            for path in created:
                path.unlink(missing_ok=True)
            raise

    @classmethod
    def create(cls, name: str, description: str = "", root=None) -> "ProgramStore":
        base = programs_root(root)
        path = unique_dir(base, slugify(name))
        store = cls(path)
        store._db.execute(
            "INSERT INTO program(id, name, slug, description, created) VALUES (1, ?, ?, ?, ?)",
            (name, path.name, description, _now()),
        )
        return store

    @classmethod
    def open(cls, slug: str, root=None) -> "ProgramStore":
        path = programs_root(root) / slug
        if not (path / DB_NAME).exists():
            raise FileNotFoundError(f"no program at {path}")
        return cls(path)

    @staticmethod
    def list(root=None) -> list:
        out = []
        for db_path in sorted(programs_root(root).glob(f"*/{DB_NAME}")):
            try:
                con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
                con.row_factory = sqlite3.Row
                row = con.execute("SELECT name, slug, description, created FROM program").fetchone()
                con.close()
            except sqlite3.Error:
                continue
            if row:
                out.append(dict(row))
        return out

    def close(self):
        with self._lock:
            self._db.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    @contextmanager
    def transaction(self):
        with self._lock:
            nested = self._db.in_transaction
            self._db.execute("SAVEPOINT store_nested" if nested else "BEGIN IMMEDIATE")
            try:
                yield self._db
            except Exception:
                self._db.execute("ROLLBACK TO store_nested" if nested else "ROLLBACK")
                if nested:
                    self._db.execute("RELEASE store_nested")
                raise
            self._db.execute("RELEASE store_nested" if nested else "COMMIT")

    def _one(self, sql, args=()):
        with self._lock:
            return _row(self._db.execute(sql, args).fetchone())

    def _all(self, sql, args=()):
        with self._lock:
            return [_row(r) for r in self._db.execute(sql, args).fetchall()]

    @property
    def info(self) -> dict:
        return self._one("SELECT * FROM program WHERE id = 1")

    def get_meta(self, key: str, default=None):
        row = self._one("SELECT value FROM meta WHERE key = ?", (key,))
        if not row:
            return default
        try:
            return json.loads(row["value"])
        except (TypeError, ValueError):
            return row["value"]

    def set_meta(self, key: str, value):
        with self.transaction() as db:
            db.execute("INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)", (key, json.dumps(value)))

    @property
    def schema_version(self) -> int:
        return SCHEMA_VERSION

    def add_session(self, mode: str = "burst", region: str | None = None, note: str = "") -> int:
        with self.transaction() as db:
            return db.execute(
                "INSERT INTO capture_session(started, mode, region, note) VALUES (?, ?, ?, ?)",
                (_now(), mode, region, note),
            ).lastrowid

    def add_evidence(self, src, session_id: int | None = None, phash: str | None = None, ext: str = "png") -> int:
        data = src if isinstance(src, (bytes, bytearray)) else robust.read_bytes(src)
        if not isinstance(src, (bytes, bytearray)):
            ext = Path(src).suffix.lstrip(".") or ext
        digest = hashlib.sha256(data).hexdigest()
        existing = self._one("SELECT id FROM evidence WHERE sha256 = ?", (digest,))
        if not isinstance(src,(bytes,bytearray)):
            from core.spacing import calibration_for
            calibration=calibration_for(src)
            if calibration.get('image_sha256')==digest:
                target=self.evidence_dir / ((existing['path'] if existing else f'{digest}.{ext}'))
                target.with_suffix('.spacing.json').write_text(json.dumps(calibration))
        if existing:
            return existing["id"]
        dest = self.evidence_dir / f"{digest}.{ext}"
        if isinstance(src, (bytes, bytearray)):
            robust.write_bytes(dest, data)
        else:
            robust.copyfile(src, dest)
        width, height = _image_size(dest)
        with self.transaction() as db:
            return db.execute(
                "INSERT INTO evidence(sha256, path, phash, width, height, session_id, captured_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (digest, dest.name, phash, width, height, session_id, _now()),
            ).lastrowid

    def evidence(self, evidence_id: int) -> dict | None:
        row = self._one("SELECT * FROM evidence WHERE id = ?", (evidence_id,))
        if row:
            row["abs_path"] = str(self.evidence_dir / row["path"])
        return row

    def add_artifact(self, name: str, artifact_type: str = "code", language: str = "",
                     transcription: str = "", evidence_ids=(), status: str = "transcribed") -> int:
        check_kind(artifact_type, ARTIFACT_TYPES, "artifact type")
        check_kind(status, ARTIFACT_STATUSES, "artifact status")
        import uuid
        source = self.sources_dir / f"{uuid.uuid4().hex}.source"
        source.write_text(transcription or "")
        now = _now()
        try:
            with self.transaction() as db:
                previous = self.current_artifact(name)
                version = previous["version"] + 1 if previous else 1
                if previous:
                    self.clear_artifact(previous["id"])
                    db.execute("UPDATE artifact SET is_current=0, status='superseded', updated=? WHERE id=?",
                               (now, previous["id"]))
                artifact_id = db.execute(
                    "INSERT INTO artifact(name, artifact_type, language, version, supersedes_id, is_current, "
                    "status, transcription, source_path, created, updated) VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?)",
                    (name, artifact_type, language, version, previous["id"] if previous else None,
                     status, transcription or "", source.name, now, now)).lastrowid
                for order, evidence_id in enumerate(evidence_ids):
                    db.execute("INSERT OR IGNORE INTO artifact_evidence(artifact_id,evidence_id,ord) VALUES (?,?,?)",
                               (artifact_id, evidence_id, order))
        except Exception:
            source.unlink(missing_ok=True)
            raise
        return artifact_id

    def rename_artifact(self, artifact_id: int, new_name: str):
        new_name = (new_name or "").strip()
        artifact = self.artifact(artifact_id)
        if artifact is None or not new_name or new_name == artifact["name"]:
            return
        if self.current_artifact(new_name):
            raise ValueError(f"a file named {new_name!r} already exists")
        old_key, new_key = f"file:{artifact['name']}", f"file:{new_name}"
        with self.transaction() as db:
            db.execute("UPDATE artifact SET name = ?, updated = ? WHERE name = ?", (new_name, _now(), artifact["name"]))
            db.execute("UPDATE entity SET key = ?, name = ?, updated = ? WHERE key = ?",
                       (new_key, new_name, _now(), old_key))
            pending = self.get_meta("pending_captures", {}) or {}
            for info in pending.values():
                if info.get("recapture_of") == artifact["name"]:
                    info["recapture_of"] = new_name
            self.set_meta("pending_captures", pending)
            target = self.get_meta("recapture_target")
            if isinstance(target, dict):
                for field in ("name", "recapture_of"):
                    if target.get(field) == artifact["name"]:
                        target[field] = new_name
                self.set_meta("recapture_target", target)
            elif target == artifact["name"]:
                self.set_meta("recapture_target", new_name)
            for row in db.execute("SELECT id,payload FROM correction").fetchall():
                payload = json.loads(row["payload"])
                if payload.get("artifact") == artifact["name"]:
                    payload["artifact"] = new_name
                    db.execute("UPDATE correction SET payload=? WHERE id=?", (json.dumps(payload), row["id"]))


    # --- captures: every start/stop of a capture is its own file, saved before analysis ---
    @property
    def text_cache_dir(self) -> Path:
        """Per-screenshot transcriptions, so re-analysing a file with extra screenshots only pays for the new ones."""
        d = self.evidence_dir / ".text"
        d.mkdir(exist_ok=True)
        return d

    def unique_name(self, name: str, exclude_id: int | None = None) -> str:
        name = (name or "capture").strip() or "capture"
        taken = {a["name"] for a in self.artifacts() if a["id"] != exclude_id}
        if name not in taken:
            return name
        stem, dot, ext = name.rpartition(".") if "." in name else (name, "", "")
        n = 2
        while True:
            cand = f"{stem} ({n}).{ext}" if dot else f"{name} ({n})"
            if cand not in taken:
                return cand
            n += 1

    def verification(self, artifact_id=None):
        """The line check of each file (core.verify.summarize), keyed by artifact id."""
        allv = self.get_meta("verification") or {}
        return allv if artifact_id is None else allv.get(str(artifact_id))

    def set_verification(self, artifact_id, v):
        with self.transaction():
            allv = self.get_meta("verification") or {}
            if v and v.get("flags"):
                try:
                    from core.model import confirmed
                    art = self.artifact(artifact_id)
                    kept = confirmed.keep_unconfirmed(self, art["name"], art.get("transcription"), v["flags"])
                    if len(kept) != len(v["flags"]):
                        v = dict(v, flags=kept, flagged=max(0, int(v.get("flagged") or 0) - (len(v["flags"]) - len(kept))))
                except Exception:
                    pass
            if v:
                allv[str(artifact_id)] = v
            else:
                allv.pop(str(artifact_id), None)
            self.set_meta("verification", allv)

    def pending_captures(self) -> dict:
        return {int(k): v for k, v in (self.get_meta("pending_captures", {}) or {}).items()}

    def _set_pending(self, artifact_id: int, info: dict | None):
        with self.transaction():
            pend = self.get_meta("pending_captures", {}) or {}
            if info is None:
                pend.pop(str(artifact_id), None)
            else:
                pend[str(artifact_id)] = info
            self.set_meta("pending_captures", pend)

    def add_pending_capture(self, images, kind: str = "code", session_id: int | None = None,
                            recapture_of: str | None = None, keep_frames_of: int | None = None) -> int:
        """Save a finished capture as a file straight away (status 'captured'), before any analysis runs, so a
        stopped or restarted capture worker can never lose it. Analysis later fills it in (complete_capture)."""
        with self.transaction():
            target = self.current_artifact(recapture_of) if recapture_of else None
            if recapture_of and target is None:
                raise ValueError("The recapture target was removed. Choose a current file before retrying.")
            if keep_frames_of and (not target or target['id'] != keep_frames_of):
                raise ValueError("The append target has been replaced. Choose the current file before retrying.")
            evidence_ids = [e["id"] for e in self.artifact_evidence(keep_frames_of)] if keep_frames_of else []
            evidence_ids += [i for i in (self.add_evidence(Path(p), session_id=session_id) for p in images)
                             if i not in evidence_ids]
            stamp = datetime.now().strftime("%Y-%m-%d %H-%M-%S")
            name = self.unique_name(f"Capture {stamp}" + (" (screen)" if kind == "screen" else ""))
            artifact_id = self.add_artifact(name, "ui_screen" if kind == "screen" else "code", "", "",
                                            evidence_ids=evidence_ids, status="captured")
            self._set_pending(artifact_id, {"kind": kind, "provisional_name": name, "recapture_of": recapture_of,
                                            "recapture_target_id": target['id'] if target else None,
                                            "recapture_target_hash": hashlib.sha256((target['transcription'] or '').encode()).hexdigest() if target else None,
                                            "added_to": keep_frames_of,
                                            "created": _now(), "attempts": 0, "error": None, "claim": None})
            return artifact_id

    def update_pending(self, artifact_id: int, **changes):
        with self.transaction():
            info = self.pending_captures().get(artifact_id)
            if info is not None:
                info.update(changes)
                self._set_pending(artifact_id, info)

    def retry_pending(self, artifact_id):
        with self.transaction() as db:
            info = self.pending_captures().get(artifact_id)
            if info is None:
                raise ValueError("Only an unanalysed capture can be retried.")
            if info.get('capture_incomplete'):
                raise RuntimeError("Screen capture was interrupted. Recapture the file or add the missing screenshots; retrying analysis cannot restore unsaved frames.")
            claim = info.get("claim") or {}
            if claim and _owner_alive(claim.get("owner")):
                raise RuntimeError("This capture is being analysed. Wait for it to finish before retrying.")
            info.update(error=None, claim=None, stage=None)
            self._set_pending(artifact_id, info)
            db.execute("UPDATE artifact SET status='captured',updated=? WHERE id=?", (_now(), artifact_id))

    def clear_pending(self, artifact_id: int):
        self._set_pending(artifact_id, None)

    def claim_pending(self, artifact_id: int, owner: str, stale_after: float = 900.0) -> bool:
        """Never reclaim work from a live process solely because it takes a long time."""
        import time as _time
        with self.transaction() as db:
            if not db.execute("SELECT 1 FROM artifact WHERE id=? AND status='captured'", (artifact_id,)).fetchone():
                return False
            info = self.pending_captures().get(artifact_id)
            if info is None:
                return False
            claim = info.get("claim") or {}
            if (claim and claim.get("owner") != owner and _owner_alive(claim.get("owner"))
                    ):
                return False
            info["claim"] = {"owner": owner, "at": _time.time()}
            info["attempts"] = int(info.get("attempts") or 0) + 1
            pending = self.get_meta("pending_captures", {}) or {}
            pending[str(artifact_id)] = info
            db.execute("INSERT OR REPLACE INTO meta(key,value) VALUES ('pending_captures',?)", (json.dumps(pending),))
            return True

    def fill_artifact(self, artifact_id: int, *, artifact_type: str, language: str, transcription: str,
                      status: str = "transcribed"):
        check_kind(artifact_type, ARTIFACT_TYPES, "artifact type")
        check_kind(status, ARTIFACT_STATUSES, "artifact status")
        art = self.artifact(artifact_id)
        if art is None:
            raise ValueError("No such artifact")
        import uuid
        source = self.sources_dir / f"{uuid.uuid4().hex}.source"
        source.write_text(transcription or "")
        old_source = art.get("source_path")
        try:
            with self.transaction() as db:
                db.execute("UPDATE artifact SET artifact_type = ?, language = ?, transcription = ?, source_path = ?, "
                           "status = ?, updated = ? WHERE id = ?",
                           (artifact_type, language or "", transcription or "", source.name, status, _now(), artifact_id))
        except Exception:
            source.unlink(missing_ok=True)
            raise
        if old_source and old_source != source.name and not self._one(
                "SELECT 1 FROM artifact WHERE source_path = ?", (old_source,)):
            (self.sources_dir / old_source).unlink(missing_ok=True)

    def model_stamp(self) -> str:
        """Changes whenever something the report depends on changes: files, corrections, staff inputs, reviewed findings."""
        import hashlib as _h
        sources = self._all("SELECT id,name,version,updated,transcription FROM artifact WHERE is_current=1 ORDER BY id")
        for source in sources:
            source["transcription"] = _h.sha256((source["transcription"] or "").encode()).hexdigest()
        parts = [sources,
                 self._all("SELECT id,kind,key,name,attrs,origin FROM entity ORDER BY id"),
                 self._all("SELECT id,kind,from_id,to_id,attrs,origin FROM relation ORDER BY id"),
                 self._all("SELECT id, active FROM correction ORDER BY id"),
                 self._all("SELECT title, status FROM finding WHERE status != 'open' OR origin != 'auto' ORDER BY title"),
                 self.get_meta("assessment_inputs", {}),
                 self.get_meta("verification", {}),
                 {k: v for k, v in self.get_meta("report_settings", {}).items() if k != "signed_off_basis"},
                 self.get_meta("transcription_benchmark", {}),
                 self.get_meta("source_layout_validation", {}),
                 {k: (v or {}).get("ran_at") for k, v in (self.get_meta("deepdive", {}) or {}).items()},
                 (self.get_meta("deepdive_program", {}) or {}).get("ran_at")]
        return _h.sha1(json.dumps(parts, sort_keys=True, default=str).encode()).hexdigest()[:16]

    def capture_progress(self, artifact_id: int) -> dict:
        """How far a waiting capture has got: screenshots read so far, and whether a worker is on it now."""
        frames = self.artifact_evidence(artifact_id)
        text = self.evidence_dir / ".text"
        info = self.pending_captures().get(artifact_id) or {}
        # Workers read into a session cache and copy it to the program only after
        # analysis finishes. Count those completed reads while the work is live.
        caches = [text]
        if info.get("cache_dir"):
            caches.append(Path(info["cache_dir"]))
        read = sum(1 for e in frames if any((cache / f"{e['sha256']}.md").is_file() for cache in caches))
        claim = info.get("claim") or {}
        return {"frames": len(frames), "read": read, "stage": info.get("stage"),
                "analysing": bool(claim) and _owner_alive(claim.get("owner"))}

    def repoint_runs(self, old_id: int, new_id: int):
        with self.transaction() as db:
            db.execute("UPDATE run SET artifact_id = ? WHERE artifact_id = ?", (new_id, old_id))

    def delete_artifact(self, artifact_id: int):
        """Remove one artifact row (its evidence files stay — other captures may share them)."""
        self.clear_artifact(artifact_id)
        with self.transaction() as db:
            db.execute("DELETE FROM artifact_evidence WHERE artifact_id = ?", (artifact_id,))
            db.execute("DELETE FROM evidence_link WHERE target_type = 'artifact' AND target_id = ?", (artifact_id,))
            db.execute("DELETE FROM finding WHERE target_type = 'artifact' AND target_id = ?", (artifact_id,))
            db.execute("DELETE FROM finding WHERE target_type = 'entity' AND target_id NOT IN (SELECT id FROM entity)")
            db.execute("DELETE FROM artifact WHERE id = ?", (artifact_id,))
        self.clear_pending(artifact_id)
        if self.verification(artifact_id):
            self.set_verification(artifact_id, None)
        with self.transaction():
            deep = self.get_meta("deepdive", {}) or {}
            deep.pop(str(artifact_id), None)
            self.set_meta("deepdive", deep)
            target = self.get_meta("recapture_target") or {}
            if target.get("artifact_id") == artifact_id:
                self.set_meta("recapture_target", None)
            for key in ("assessment", "deepdive_program", "report_stamp"):
                self.set_meta(key, None)

    def export_copybooks(self) -> Path:
        target = self.path / "copybooks"
        target.mkdir(exist_ok=True)
        for artifact in self.artifacts():
            name = artifact["name"]
            if not (name.lower().endswith((".cpy", ".copy")) or "copybook" in (artifact["language"] or "").lower()):
                continue
            stem = Path(name).stem
            for variant in {stem, stem.upper()}:
                (target / f"{variant}.cpy").write_text(artifact["transcription"] or "")
        return target

    def artifact(self, artifact_id: int) -> dict | None:
        return self._one("SELECT * FROM artifact WHERE id = ?", (artifact_id,))

    def current_artifact(self, name: str) -> dict | None:
        return self._one("SELECT * FROM artifact WHERE name = ? AND is_current = 1", (name,))

    def artifacts(self, current_only: bool = True) -> list:
        where = "WHERE is_current = 1" if current_only else ""
        return self._all(f"SELECT * FROM artifact {where} ORDER BY name, version")

    def artifact_evidence(self, artifact_id: int) -> list:
        return self._all(
            "SELECT e.*, ae.ord, ae.region FROM artifact_evidence ae JOIN evidence e ON e.id = ae.evidence_id "
            "WHERE ae.artifact_id = ? ORDER BY ae.ord",
            (artifact_id,),
        )

    def set_artifact_type(self, artifact_id: int, artifact_type: str):
        check_kind(artifact_type, ARTIFACT_TYPES, "artifact type")
        with self.transaction() as db:
            db.execute("UPDATE artifact SET artifact_type = ?, updated = ? WHERE id = ?",
                       (artifact_type, _now(), artifact_id))

    def set_status(self, artifact_id: int, status: str):
        check_kind(status, ARTIFACT_STATUSES, "artifact status")
        with self.transaction() as db:
            db.execute("UPDATE artifact SET status = ?, updated = ? WHERE id = ?", (status, _now(), artifact_id))

    def set_validation(self, artifact_id: int, tool: str, ok: bool, errors: str = ""):
        with self.transaction() as db:
            db.execute(
                "UPDATE artifact SET validation_tool = ?, validation_ok = ?, validation_errors = ?, "
                "status = CASE WHEN status IN ('captured', 'transcribed') THEN 'validated' ELSE status END, "
                "updated = ? WHERE id = ?",
                (tool, None if ok is None else int(bool(ok)), errors or "", _now(), artifact_id),
            )

    def upsert_entity(self, kind: str, name: str, *, key: str | None = None, parent_id: int | None = None,
                      attrs: dict | None = None, artifact_id: int | None = None, line_start: int | None = None,
                      line_end: int | None = None, confidence: float = 1.0, origin: str = "extracted") -> int:
        check_kind(kind, ENTITY_KINDS, "entity kind")
        check_kind(origin, ORIGINS, "origin")
        clean = validate_attrs(kind, attrs)
        parent_key = self.entity(parent_id)["key"] if parent_id else None
        key = key or entity_key(kind, name, parent_key)
        now = _now()
        with self.transaction() as db:
            existing = _row(db.execute("SELECT * FROM entity WHERE key = ?", (key,)).fetchone())
            if existing is None:
                entity_id = db.execute(
                    "INSERT INTO entity(kind, key, name, parent_id, attrs, artifact_id, line_start, line_end, "
                    "confidence, origin, created, updated) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (kind, key, name, parent_id, json.dumps(clean), artifact_id, line_start, line_end,
                     confidence, origin, now, now),
                ).lastrowid
            else:
                entity_id = existing["id"]
                upgrade = existing["origin"] == "placeholder" and origin != "placeholder"
                if existing["origin"] != "corrected" and origin != "placeholder":
                    merged = {**existing["attrs"], **clean}
                    db.execute(
                        "UPDATE entity SET name = CASE WHEN ? THEN ? ELSE name END, "
                        "attrs = ?, parent_id = COALESCE(?, parent_id), "
                        "artifact_id = CASE WHEN ? THEN ? ELSE COALESCE(artifact_id, ?) END, "
                        "line_start = CASE WHEN ? THEN ? ELSE COALESCE(line_start, ?) END, "
                        "line_end = CASE WHEN ? THEN ? ELSE COALESCE(line_end, ?) END, "
                        "confidence = MAX(confidence, ?), "
                        "origin = CASE WHEN ? = 'corrected' OR origin = 'placeholder' THEN ? ELSE origin END, "
                        "updated = ? WHERE id = ?",
                        (upgrade, name, json.dumps(merged), parent_id, upgrade, artifact_id, artifact_id,
                         upgrade, line_start, line_start, upgrade, line_end, line_end,
                         confidence, origin, origin, now, entity_id),
                    )
            if artifact_id is not None and origin != "placeholder":
                db.execute(
                    "INSERT INTO entity_source(entity_id, artifact_id, line_start, line_end) VALUES (?, ?, ?, ?)",
                    (entity_id, artifact_id, line_start, line_end),
                )
        return entity_id

    def entity(self, entity_id: int) -> dict | None:
        return self._one("SELECT * FROM entity WHERE id = ?", (entity_id,))

    def entity_by_key(self, key: str) -> dict | None:
        return self._one("SELECT * FROM entity WHERE key = ?", (key,))

    def find(self, name: str, kinds=None) -> list:
        sql, args = "SELECT * FROM entity WHERE name = ? COLLATE NOCASE", [name]
        if kinds:
            kinds = list(kinds)
            sql += f" AND kind IN ({','.join('?' * len(kinds))})"
            args += kinds
        return self._all(sql, args)

    def entities(self, kind: str | None = None, origin: str | None = None) -> list:
        sql, args = "SELECT * FROM entity WHERE 1 = 1", []
        if kind:
            sql, args = sql + " AND kind = ?", args + [kind]
        if origin:
            sql, args = sql + " AND origin = ?", args + [origin]
        return self._all(sql + " ORDER BY kind, key", args)

    def entity_sources(self, entity_id: int) -> list:
        return self._all(
            "SELECT es.*, a.name AS artifact_name FROM entity_source es JOIN artifact a ON a.id = es.artifact_id "
            "WHERE es.entity_id = ?",
            (entity_id,),
        )

    def resolve(self, ref, kind_hint: str | None = None, create: bool = True) -> int | None:
        if isinstance(ref, int):
            return ref
        ref = str(ref).strip()
        if ":" in ref and ref.split(":", 1)[0] in ENTITY_KINDS:
            found = self.entity_by_key(ref)
            if found:
                return found["id"]
            kind, name = ref.split(":", 1)
            return self.upsert_entity(kind, name, key=ref, origin="placeholder") if create else None
        matches = self.find(ref, [kind_hint] if kind_hint else None)
        if len(matches) == 1:
            return matches[0]["id"]
        real = [m for m in matches if m["origin"] != "placeholder"]
        if len(real) == 1:
            return real[0]["id"]
        if not create:
            return None
        return self.upsert_entity(kind_hint or "unknown", ref, origin="placeholder")

    def add_relation(self, kind: str, source, target, *, artifact_id: int | None = None, line: int | None = None,
                     attrs: dict | None = None, confidence: float = 1.0, origin: str = "extracted",
                     source_kind: str | None = None, target_kind: str | None = None) -> int:
        check_kind(kind, RELATION_KINDS, "relation kind")
        check_kind(origin, ORIGINS, "origin")
        from_id = self.resolve(source, source_kind)
        to_id = self.resolve(target, target_kind)
        with self.transaction() as db:
            existing = db.execute(
                "SELECT id FROM relation WHERE kind = ? AND from_id = ? AND to_id = ? AND artifact_id IS ?",
                (kind, from_id, to_id, artifact_id),
            ).fetchone()
            if existing:
                return existing["id"]
            return db.execute(
                "INSERT INTO relation(kind, from_id, to_id, attrs, artifact_id, line, confidence, origin, created) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (kind, from_id, to_id, json.dumps(attrs or {}), artifact_id, line, confidence, origin, _now()),
            ).lastrowid

    def relations(self, kind: str | None = None, from_id: int | None = None, to_id: int | None = None) -> list:
        sql, args = "SELECT * FROM relation WHERE 1 = 1", []
        for column, value in (("kind", kind), ("from_id", from_id), ("to_id", to_id)):
            if value is not None:
                sql, args = sql + f" AND {column} = ?", args + [value]
        return self._all(sql + " ORDER BY id", args)

    def neighbors(self, entity_id: int, direction: str = "out", kind: str | None = None) -> list:
        column, other = ("from_id", "to_id") if direction == "out" else ("to_id", "from_id")
        sql = f"SELECT DISTINCT e.* FROM relation r JOIN entity e ON e.id = r.{other} WHERE r.{column} = ?"
        args = [entity_id]
        if kind:
            sql, args = sql + " AND r.kind = ?", args + [kind]
        return self._all(sql, args)

    def clear_artifact(self, artifact_id: int):
        with self.transaction() as db:
            touched = {r[0] for r in db.execute(
                "SELECT entity_id FROM entity_source WHERE artifact_id = ? "
                "UNION SELECT id FROM entity WHERE artifact_id = ?", (artifact_id, artifact_id))}
            db.execute("DELETE FROM relation WHERE artifact_id = ? AND origin != 'corrected'", (artifact_id,))
            db.execute("DELETE FROM entity_source WHERE artifact_id = ?", (artifact_id,))
            for entity_id in touched:
                entity = db.execute("SELECT origin, artifact_id FROM entity WHERE id = ?", (entity_id,)).fetchone()
                if entity is None or entity["origin"] not in ("extracted", "inferred"):
                    continue
                remaining = db.execute(
                    "SELECT artifact_id, line_start, line_end FROM entity_source WHERE entity_id = ? LIMIT 1",
                    (entity_id,),
                ).fetchone()
                if remaining:
                    if entity["artifact_id"] == artifact_id:
                        db.execute(
                            "UPDATE entity SET artifact_id = ?, line_start = ?, line_end = ?, updated = ? WHERE id = ?",
                            (remaining["artifact_id"], remaining["line_start"], remaining["line_end"], _now(), entity_id),
                        )
                    continue
                referenced = db.execute(
                    "SELECT 1 FROM relation WHERE from_id = ? OR to_id = ? LIMIT 1", (entity_id, entity_id)
                ).fetchone()
                if referenced:
                    db.execute(
                        "UPDATE entity SET origin = 'placeholder', artifact_id = NULL, line_start = NULL, "
                        "line_end = NULL, updated = ? WHERE id = ?",
                        (_now(), entity_id),
                    )
                else:
                    db.execute("DELETE FROM entity WHERE id = ?", (entity_id,))

    def link_evidence(self, target_type: str, target_id: int, evidence_id: int, region: str | None = None):
        with self.transaction() as db:
            db.execute(
                "INSERT OR REPLACE INTO evidence_link(target_type, target_id, evidence_id, region) VALUES (?, ?, ?, ?)",
                (target_type, target_id, evidence_id, region),
            )

    def evidence_for(self, target_type: str, target_id: int) -> list:
        rows = self._all(
            "SELECT e.*, l.region FROM evidence_link l JOIN evidence e ON e.id = l.evidence_id "
            "WHERE l.target_type = ? AND l.target_id = ?",
            (target_type, target_id),
        )
        if target_type == "entity":
            seen = {r["id"] for r in rows}
            for source in self.entity_sources(target_id):
                for ev in self.artifact_evidence(source["artifact_id"]):
                    if ev["id"] not in seen:
                        seen.add(ev["id"])
                        rows.append(ev)
        elif target_type == "artifact":
            rows += [ev for ev in self.artifact_evidence(target_id) if ev["id"] not in {r["id"] for r in rows}]
        return rows

    def add_finding(self, category: str, severity: str, title: str, *, detail: str = "", source: str = "",
                    target_type: str | None = None, target_id: int | None = None, evidence=(), rule: str | None = None,
                    refs: dict | None = None, status: str = "open", origin: str = "auto") -> int:
        with self.transaction() as db:
            return db.execute(
                "INSERT INTO finding(target_type, target_id, category, severity, title, detail, source, evidence, "
                "created, rule, refs, status, origin) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (target_type, target_id, category, severity, title, detail, source, json.dumps(list(evidence)), _now(),
                 rule, json.dumps(refs or {}), status, origin),
            ).lastrowid

    def findings(self, category: str | None = None) -> list:
        if category:
            return self._all("SELECT * FROM finding WHERE category = ? ORDER BY id", (category,))
        return self._all("SELECT * FROM finding ORDER BY id")

    def finding(self, finding_id: int) -> dict | None:
        return self._one("SELECT * FROM finding WHERE id = ?", (finding_id,))

    def clear_findings(self, categories, origin: str = "auto", keep_source_prefix: str | None = None) -> int:
        cats = list(categories)
        sql = f"DELETE FROM finding WHERE origin = ? AND category IN ({','.join('?' * len(cats))})"
        args = [origin, *cats]
        if keep_source_prefix:
            sql += " AND source NOT LIKE ?"
            args.append(keep_source_prefix + "%")
        with self.transaction() as db:
            return db.execute(sql, args).rowcount

    def set_finding_status(self, finding_id: int, status: str):
        with self.transaction() as db:
            db.execute("UPDATE finding SET status = ? WHERE id = ?", (status, finding_id))

    def add_correction(self, target_type: str, target_id: int | None, op: str, payload: dict | None = None,
                       note: str = "") -> int:
        with self.transaction() as db:
            return db.execute(
                "INSERT INTO correction(target_type, target_id, op, payload, note, created) VALUES (?, ?, ?, ?, ?, ?)",
                (target_type, target_id, op, json.dumps(payload or {}), note, _now()),
            ).lastrowid

    def correction(self, correction_id: int) -> dict | None:
        return self._one("SELECT * FROM correction WHERE id = ?", (correction_id,))

    def update_correction(self, correction_id: int, *, payload: dict | None = None, active: bool | None = None):
        with self.transaction() as db:
            if payload is not None:
                db.execute("UPDATE correction SET payload = ? WHERE id = ?", (json.dumps(payload), correction_id))
            if active is not None:
                db.execute("UPDATE correction SET active = ? WHERE id = ?", (int(active), correction_id))

    def corrections(self, active_only: bool = True) -> list:
        where = "WHERE active = 1" if active_only else ""
        return self._all(f"SELECT * FROM correction {where} ORDER BY id")

    def log_run(self, step: str, *, artifact_id: int | None = None, model: str | None = None,
                prompt_version: str | None = None, input_tokens: int | None = None, output_tokens: int | None = None,
                cost: float | None = None, ms: int | None = None, ok: bool = True, error: str | None = None) -> int:
        with self.transaction() as db:
            return db.execute(
                "INSERT INTO run(step, artifact_id, model, prompt_version, input_tokens, output_tokens, cost, ms, ok, "
                "error, created) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (step, artifact_id, model, prompt_version, input_tokens, output_tokens, cost, ms, int(ok), error, _now()),
            ).lastrowid

    def log_usage_record(self, record, artifact_id=None):
        with self.transaction() as db:
            db.execute("CREATE TABLE IF NOT EXISTS usage_receipt(call_id TEXT PRIMARY KEY, run_id INTEGER)")
            call_id = record.get("call_id")
            if call_id:
                existing = db.execute("SELECT run_id FROM usage_receipt WHERE call_id=?", (call_id,)).fetchone()
                if existing:
                    db.execute("UPDATE run SET step=? WHERE id=?", (record["step"], existing[0]))
                    if artifact_id is not None:
                        db.execute("UPDATE run SET artifact_id=? WHERE id=?", (artifact_id, existing[0]))
                    return existing[0]
            run_id = self.log_run(record["step"], artifact_id=artifact_id,
                                  **{k: record.get(k) for k in ("model", "input_tokens", "output_tokens", "cost", "ms", "ok", "error")})
            if call_id:
                db.execute("INSERT INTO usage_receipt VALUES (?,?)", (call_id, run_id))
            return run_id

    def runs(self) -> list:
        return self._all("SELECT * FROM run ORDER BY id")

    def usage(self) -> dict:
        row = self._one(
            "SELECT COUNT(*) AS calls, COALESCE(SUM(input_tokens), 0) AS input_tokens, "
            "COALESCE(SUM(output_tokens), 0) AS output_tokens, COALESCE(SUM(cost), 0) AS cost, "
            "COALESCE(SUM(ms), 0) AS ms, COALESCE(SUM(1 - ok), 0) AS failures FROM run"
        )
        return row

    def usage_by_step(self) -> dict:
        rows = self._all(
            "SELECT step, model, COUNT(*) AS calls, COALESCE(SUM(input_tokens), 0) AS input_tokens, "
            "COALESCE(SUM(output_tokens), 0) AS output_tokens, COALESCE(SUM(cost), 0) AS cost, "
            "COALESCE(SUM(ms), 0) AS ms FROM run GROUP BY step, model ORDER BY cost DESC"
        )
        return {"steps": rows, "files": self._all(
            "SELECT a.name, COALESCE(SUM(r.cost), 0) AS cost, COALESCE(SUM(r.input_tokens), 0) AS input_tokens, "
            "COALESCE(SUM(r.output_tokens), 0) AS output_tokens, COUNT(r.id) AS calls FROM artifact a "
            "LEFT JOIN run r ON r.artifact_id = a.id WHERE a.is_current = 1 OR r.id IS NOT NULL "
            "GROUP BY a.name ORDER BY cost DESC")}

    def artifact_cost(self, artifact_id: int) -> float:
        row = self._one("SELECT COALESCE(SUM(r.cost), 0) AS cost FROM run r JOIN artifact a ON a.id = r.artifact_id "
                        "WHERE a.name = (SELECT name FROM artifact WHERE id = ?)", (artifact_id,))
        return round(row["cost"], 4) if row else 0.0

    def merge_entities(self, source_id: int, target_id: int, rule: str = ""):
        if source_id == target_id:
            return
        src, dst = self.entity(source_id), self.entity(target_id)
        if src is None or dst is None:
            return
        with self.transaction() as db:
            db.execute("UPDATE relation SET from_id = ? WHERE from_id = ?", (target_id, source_id))
            db.execute("UPDATE relation SET to_id = ? WHERE to_id = ?", (target_id, source_id))
            db.execute("UPDATE entity_source SET entity_id = ? WHERE entity_id = ?", (target_id, source_id))
            db.execute("UPDATE OR IGNORE evidence_link SET target_id = ? WHERE target_type = 'entity' AND target_id = ?",
                       (target_id, source_id))
            db.execute("UPDATE entity SET parent_id = ? WHERE parent_id = ?", (target_id, source_id))
            db.execute("DELETE FROM relation WHERE from_id = to_id AND from_id = ?", (target_id,))
            db.execute(
                "DELETE FROM relation WHERE id IN (SELECT r.id FROM relation r JOIN relation k ON k.kind = r.kind "
                "AND k.from_id = r.from_id AND k.to_id = r.to_id AND k.artifact_id IS r.artifact_id AND k.id < r.id "
                "WHERE r.from_id = ? OR r.to_id = ?)", (target_id, target_id))
            aliases = sorted(set(dst["attrs"].get("aliases", [])) | {src["key"]})
            attrs = {**dst["attrs"], "aliases": aliases}
            db.execute("UPDATE entity SET attrs = ?, updated = ? WHERE id = ?", (json.dumps(attrs), _now(), target_id))
            db.execute("DELETE FROM entity WHERE id = ?", (source_id,))

    def coverage(self) -> dict:
        by_status = {r["status"]: r["n"] for r in self._all(
            "SELECT status, COUNT(*) AS n FROM artifact WHERE is_current = 1 GROUP BY status")}
        by_kind = {r["kind"]: r["n"] for r in self._all(
            "SELECT kind, COUNT(*) AS n FROM entity WHERE origin != 'placeholder' GROUP BY kind")}
        missing = []
        for placeholder in self.entities(origin="placeholder"):
            referrers = self._all(
                "SELECT DISTINCT e.name, e.kind, r.kind AS relation, a.name AS artifact FROM relation r "
                "JOIN entity e ON e.id = r.from_id LEFT JOIN artifact a ON a.id = r.artifact_id WHERE r.to_id = ? "
                "AND (r.artifact_id IS NULL OR a.is_current = 1)",
                (placeholder["id"],),
            )
            if not referrers:
                continue
            if self._one("SELECT 1 FROM relation WHERE kind = 'same_as' AND (from_id = ? OR to_id = ?)",
                         (placeholder["id"], placeholder["id"])):
                continue
            missing.append({"id": placeholder["id"], "kind": placeholder["kind"], "name": placeholder["name"],
                            "category": classify_placeholder(placeholder, referrers), "referenced_by": referrers})
        total = sum(by_kind.values())
        counts = {c: sum(1 for m in missing if m["category"] == c) for c in ("missing_code", "external", "library")}
        code_total = total - sum(by_kind.get(k, 0) for k in ("table", "column", "data_store", "external_system",
                                                             "config_item"))
        denom = code_total + counts["missing_code"]
        return {
            "files": sum(by_status.values()),
            "files_by_status": by_status,
            "entities": total,
            "entities_by_kind": by_kind,
            "missing": missing,
            "missing_counts": counts,
            "resolved_ratio": round(code_total / denom, 3) if denom and code_total else (None if not total else 1.0),
        }

    def graph(self) -> dict:
        nodes = [{"id": e["id"], "kind": e["kind"], "name": e["name"], "key": e["key"], "origin": e["origin"],
                  "parent_id": e["parent_id"]} for e in self.entities()]
        edges = [{"id": r["id"], "kind": r["kind"], "from": r["from_id"], "to": r["to_id"], "origin": r["origin"]}
                 for r in self.relations()]
        return {"nodes": nodes, "edges": edges}

    def export(self, write: bool = True) -> dict:
        data = {
            "schema_version": SCHEMA_VERSION,
            "exported": _now(),
            "program": self.info,
            "artifacts": [{k: v for k, v in a.items() if k != "transcription"} | {
                "evidence": [e["path"] for e in self.artifact_evidence(a["id"])]} for a in self.artifacts()],
            "entities": self.entities(),
            "relations": self.relations(),
            "findings": self.findings(),
            "corrections": self.corrections(active_only=False),
            "coverage": self.coverage(),
            "usage": self.usage(),
            "assessment_inputs": self.get_meta("assessment_inputs", {}),
            "assessment": self.get_meta("assessment"),
        }
        if write:
            (self.exports_dir / "program.json").write_text(json.dumps(data, indent=2))
        return data


def classify_placeholder(entity: dict, referrers=()) -> str:
    from .linker import classify
    return classify(entity, referrers)


def _image_size(path: Path):
    try:
        from PIL import Image
        with Image.open(path) as im:
            return im.size
    except Exception:
        return None, None
