"""User removal purges a file and its history; internal version replacement stays separate."""
import hashlib
import json
import time
from pathlib import Path

from .store import _owner_alive

CAPTURE_ROOT = Path(__file__).resolve().parents[3] / "captures"


def remove_file(store, artifact_id):
    paths, screenshots = [], {}
    with store.transaction() as db:
        def meta(key, default=None):
            row = db.execute('SELECT value FROM meta WHERE key = ?', (key,)).fetchone()
            return json.loads(row[0]) if row else default

        def put(key, value):
            db.execute('INSERT OR REPLACE INTO meta(key,value) VALUES (?,?)', (key, json.dumps(value)))

        artifact = db.execute('SELECT * FROM artifact WHERE id = ?', (artifact_id,)).fetchone()
        if not artifact:
            raise KeyError(artifact_id)
        pending = meta('pending_captures', {}) or {}
        if any((v.get('claim') or {}).get('owner') and _owner_alive(v['claim']['owner']) for v in pending.values()):
            raise RuntimeError('Wait for the current file analysis to finish before removing a file.')
        active = meta('deepdive_active', {}) or {}
        if any(time.time() - stamp < 1800 for stamp in active.values()):
            raise RuntimeError('Wait for the current code review to finish before removing a file.')
        names = {artifact['name']}
        ids = {r[0] for r in db.execute('SELECT id FROM artifact WHERE name = ?', (artifact['name'],))}
        ids.update(int(k) for k, v in pending.items() if v.get('recapture_of') in names or v.get('added_to') in ids)
        marks = ','.join('?' for _ in ids)
        args = tuple(ids)
        artifacts = list(db.execute(f'SELECT * FROM artifact WHERE id IN ({marks})', args))
        names.update(a['name'] for a in artifacts)
        paths.extend(store.sources_dir / a['source_path'] for a in artifacts if a['source_path'])
        evidence = list(db.execute(f'SELECT DISTINCT e.* FROM evidence e JOIN artifact_evidence ae ON ae.evidence_id=e.id WHERE ae.artifact_id IN ({marks})', args))
        touched = {r[0] for r in db.execute(f'SELECT id FROM entity WHERE artifact_id IN ({marks}) UNION SELECT entity_id FROM entity_source WHERE artifact_id IN ({marks})', args + args)}
        keys, removed_entities = set(), set()
        for eid in touched:
            other = db.execute(f'SELECT 1 FROM entity_source WHERE entity_id=? AND artifact_id NOT IN ({marks})', (eid, *args)).fetchone()
            if not other:
                removed_entities.add(eid)
                row = db.execute('SELECT key FROM entity WHERE id=?', (eid,)).fetchone()
                if row:
                    keys.add(row[0])
                db.execute("DELETE FROM finding WHERE target_type='entity' AND target_id=?", (eid,))
                db.execute("DELETE FROM evidence_link WHERE target_type='entity' AND target_id=?", (eid,))
                db.execute('DELETE FROM entity WHERE id=?', (eid,))
            else:
                replacement = db.execute(f'SELECT artifact_id,line_start,line_end FROM entity_source WHERE entity_id=? AND artifact_id NOT IN ({marks}) LIMIT 1', (eid, *args)).fetchone()
                db.execute(f'UPDATE entity SET artifact_id=?,line_start=?,line_end=? WHERE id=? AND artifact_id IN ({marks})', (*replacement, eid, *args))
        for row in list(db.execute('SELECT id,target_type,target_id,evidence FROM finding')):
            ev = json.loads(row['evidence'])
            if (row['target_type'] == 'artifact' and row['target_id'] in ids) or any(e.get('file') in names for e in ev if isinstance(e, dict)):
                db.execute('DELETE FROM finding WHERE id=?', (row['id'],))
        for row in list(db.execute('SELECT * FROM correction')):
            payload = row['payload'] or ''
            if (row['target_type'] == 'artifact' and row['target_id'] in ids) or (row['target_type'] == 'entity' and row['target_id'] in removed_entities) or any(json.dumps(k) in payload for k in keys | names):
                db.execute('DELETE FROM correction WHERE id=?', (row['id'],))
        db.execute(f"DELETE FROM evidence_link WHERE target_type='artifact' AND target_id IN ({marks})", args)
        # Keep actual API spend, but detach labels and errors belonging to the removed file.
        db.execute(f'UPDATE run SET artifact_id=NULL,error=NULL WHERE artifact_id IN ({marks})', args)
        db.execute(f'DELETE FROM artifact WHERE id IN ({marks})', args)
        for table in ('finding', 'evidence_link', 'correction'):
            for kind, target in (('entity', 'entity'), ('relation', 'relation'), ('artifact', 'artifact')):
                db.execute(f"DELETE FROM {table} WHERE target_type=? AND target_id NOT IN (SELECT id FROM {target})", (kind,))
        for key in ('pending_captures', 'verification', 'deepdive', 'deepdive_active', 'manual_capture_concerns'):
            value = meta(key, {}) or {}
            if isinstance(value, dict):
                put(key, {k: v for k, v in value.items() if str(k) not in {str(i) for i in ids} and k not in names})
        # Cross-file summaries may contain conclusions based on the removed file.
        for key in ('assessment', 'deepdive_program', 'site_scan', 'ui_flows', 'report_stamp', 'report_built_at', 'recaptures'):
            put(key, None)
        target = meta('recapture_target') or {}
        if target.get('artifact_id') in ids or target.get('name') in names:
            put('recapture_target', None)
        for ev in evidence:
            shared = db.execute('SELECT 1 FROM artifact_evidence WHERE evidence_id=? UNION SELECT 1 FROM evidence_link WHERE evidence_id=?', (ev['id'], ev['id'])).fetchone()
            if not shared:
                db.execute('DELETE FROM evidence WHERE id=?', (ev['id'],))
                paths.append(store.evidence_dir / ev['path'])
                image_path = store.evidence_dir / ev['path']
                if image_path.exists():
                    screenshots[ev['sha256']] = image_path.stat().st_size
                paths.extend(store.text_cache_dir.glob(ev['sha256'] + '*'))
    for path in paths:
        if path.is_file():
            path.unlink()
    # Every program export can contain the old inventory, diagrams or findings.
    for path in store.exports_dir.rglob('*'):
        if path.is_file():
            path.unlink()
    copybooks = store.path / 'copybooks'
    if copybooks.exists():
        for path in copybooks.glob('*.cpy'):
            path.unlink()
    # Remove scratch captures matching orphaned evidence, never the user's source files.
    capture_root = CAPTURE_ROOT
    for path in capture_root.glob('*/[0-9]*.png') if screenshots else []:
        if path.stat().st_size not in screenshots.values():
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest in screenshots:
            path.unlink()
            cache = path.parent / '.cache'
            for cached in cache.glob(digest + '*') if cache.exists() else []:
                if cached.is_file():
                    cached.unlink()
    return sorted(ids)
