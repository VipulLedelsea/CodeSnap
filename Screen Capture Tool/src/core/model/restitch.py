"""Rebuild a completed source capture locally, preserving screenshots and prior versions."""
import json
import re
import tempfile
from pathlib import Path

from core.analysis import merge_verified, _normalize_extract, source_mode, clean_source, measured_frame
from core.validate import check_source
from core.verify import summarize
from core.text import normalized_line
from .ingest import _parse_deterministic, _relink, apply_structure


def _correction_positions(store, art, code):
    """Locate accepted edits by their neighbouring source, refusing ambiguous repeats."""
    old = (art.get('transcription') or '').splitlines()
    new = code.splitlines()
    norm = normalized_line
    anchor = re.compile(r'^(?:\d{2,}-[\w-]+\.|\w+\s*:\s*PROC\b|\w+:$|\w+\s+BEGSR\b|\w+\s+DFH(?:MSD|MDI)\b)', re.I)
    def owner(lines, index):
        return next((norm(lines[k]) for k in range(min(index, len(lines)-1), -1, -1)
                     if anchor.match(norm(lines[k]))), None)
    updates = []
    for correction in store.corrections():
        p = correction['payload']
        if correction['op'] not in ('artifact.replace_line', 'artifact.confirm_line') or p.get('artifact') != art['name']:
            continue
        index = p['line'] - 1
        if correction['op'] == 'artifact.confirm_line' and (
                index >= len(old) or norm(old[index]) != norm(p['old_text'])):
            continue   # a confirmation of a line that is no longer there cannot block a rebuild
        targets = {norm(p['old_text']), norm(p.get('new_text', p['old_text']))}
        # Earlier rebases may have replaced old_text with the accepted value.
        # Saved screenshots can still contain the original reading; retain those
        # candidates, but require the same owner and unambiguous surrounding rows.
        for history in p.get('_rebase_history', []) if correction['op'] == 'artifact.replace_line' else []:
            for text in (history.get('old_text'), history.get('new_text'),
                         (history.get('before') or {}).get('text')):
                if isinstance(text, str):
                    targets.add(norm(text))
        candidates = []
        for j, text in enumerate(new):
            if norm(text) not in targets:
                continue
            owning = owner(old, index)
            if owning and owner(new, j) != owning:
                continue
            score = sum(1 for off in range(-8, 9) if off and
                        0 <= index + off < len(old) and 0 <= j + off < len(new) and
                        old[index + off].strip() and norm(old[index + off]) == norm(new[j + off]))
            candidates.append((score, j))
        candidates.sort(reverse=True)
        if not candidates or (len(candidates) > 1 and
                              (candidates[0][0] < 2 or candidates[0][0] == candidates[1][0])):
            if correction['op'] == 'artifact.confirm_line':
                continue   # still honoured by text through the saved confirmed lines
            raise ValueError(f'Cannot safely relocate your correction #{correction["id"]}. No changes were made.')
        updates.append((correction, candidates[0][1] + 1))
    return updates


def rebuild_saved_capture(store, artifact_id, progress=None):
    def update(stage, done=0, total=0):
        if progress:
            progress(stage=stage, done=done, total=total)
    art = store.artifact(artifact_id)
    if art is None:
        raise KeyError(artifact_id)
    if (store.current_artifact(art['name']) or {}).get('id') != artifact_id:
        raise ValueError('This version has been replaced. Rebuild the current file instead.')
    from core.report.quality import current_benchmark
    validated = any(row['artifact_id'] == artifact_id and row['expected'] == row['actual'] == row['matched']
                    for row in current_benchmark(store)['files'])
    from core.report.quality import source_hash
    reviewed_spacing = any(row.get('new_id') == artifact_id and
                           row.get('source_sha256') == source_hash(art.get('transcription'))
                           for row in (store.get_meta('approved_spacing_repair') or {}).get('files', []))
    from core.cobol.detect import detect_kind
    bms_source = detect_kind(art.get('transcription') or '', extension=Path(art['name']).suffix) == 'bms'
    if art['status'] == 'captured' or (art['artifact_type'] == 'ui_screen' and not bms_source):
        raise ValueError('This action needs a completed source capture. Use Retry for a waiting capture.')
    frames = store.artifact_evidence(artifact_id)
    parts, metas = [], []
    if not frames:
        raise ValueError('No saved screenshots are available for this file.')
    update('Reading saved screenshots', 0, len(frames))
    for index, frame in enumerate(frames, 1):
        cached = store.text_cache_dir / (frame['sha256'] + '.md')
        if not cached.exists():
            raise ValueError('Some screenshot text is not cached yet. No changes were made.')
        raw = cached.read_text()
        text = _normalize_extract(raw)['raw'] if '"raw_transcription"' in raw else raw
        if not text.strip():
            raise ValueError(f'Screenshot {index} has no cached readable text. No changes were made.')
        parts.append(text)
        sidecar = cached.with_suffix('.verify.json')
        metas.append(json.loads(sidecar.read_text()) if sidecar.exists() and text == raw else {})
        update('Reading saved screenshots', index, len(frames))
    mode = source_mode(parts)
    for i,(frame,text) in enumerate(zip(frames,parts)):
        path=store.evidence(frame['id'])['abs_path']
        text,checked,_=measured_frame(None,path,clean_source(text,mode))
        checked.update({key:metas[i][key] for key in ('numbers','numbers_seen','numbers_rejected') if key in metas[i]})
        parts[i],metas[i]=text,checked
    update('Stitching saved text', len(frames), len(frames))
    code, _, notes, statuses = merge_verified(parts, metas)
    if not code.strip():
        raise ValueError('The saved screenshots contain no readable source. No changes were made.')
    correction_positions = _correction_positions(store, art, code)
    parsed = _parse_deterministic(code, art)
    if parsed is None:
        raise ValueError('Local rebuilding is not available for this source format. No changes were made.')
    update('Checking rebuilt source', len(frames), len(frames))
    with tempfile.TemporaryDirectory() as directory:
        source = Path(directory) / Path(art['name']).name
        source.write_text(code + '\n')
        validation = check_source(source)
    verification = summarize(code, statuses, notes, read_code=code)
    update('Saving rebuilt analysis', len(frames), len(frames))
    with store.transaction():
        current = store.current_artifact(art['name'])
        if not current or current['id'] != artifact_id or current['transcription'] != art['transcription']:
            raise ValueError('The file changed during rebuilding. No changes were made; retry with the current file.')
        new_id = store.add_artifact(art['name'], 'code' if bms_source else art['artifact_type'], art['language'], code,
                                    evidence_ids=[frame['id'] for frame in frames])
        store.set_verification(new_id, verification)
        store.set_validation(new_id, validation['tool'], validation['ok'] if validation['checked'] else None,
                             validation['errors'] if validation['checked'] else validation['note'])
        apply_structure(store, new_id, parsed['structure'], art['name'], len(code.splitlines()))
        store.set_status(new_id, 'structured')
        for correction, line in correction_positions:
            payload = dict(correction['payload'])
            payload['_rebase_history'] = [*payload.get('_rebase_history', []),
                                         {'artifact_id': artifact_id, 'line': payload['line'],
                                          'old_text': payload.get('old_text'), 'new_text': payload.get('new_text'),
                                          'before': payload.get('_before')}]
            payload['line'] = line
            payload['_reviewed_artifact_id'] = new_id
            observed = code.splitlines()[line-1]
            if correction['op'] == 'artifact.confirm_line':
                payload['old_text'] = observed
            elif normalized_line(observed) != normalized_line(payload['new_text']):
                old_indent = len(payload['old_text']) - len(payload['old_text'].lstrip())
                new_indent = len(payload['new_text']) - len(payload['new_text'].lstrip())
                if old_indent == new_indent:
                    payload['new_text'] = observed[:len(observed)-len(observed.lstrip())] + payload['new_text'].lstrip()
                payload['old_text'] = observed
            payload.pop('_before', None)
            store.update_correction(correction['id'], payload=payload)
        _relink(store)
        # Replayed human edits are part of the source being checked, too.
        final = store.artifact(new_id)['transcription']
        if reviewed_spacing and final.splitlines() != art['transcription'].splitlines():
            raise ValueError('Rebuilding would undo reviewed source spacing. No changes were made; review the saved readings or recapture the file.')
        if validated and [normalized_line(line) for line in final.splitlines() if line.strip()] != [
                normalized_line(line) for line in art['transcription'].splitlines() if line.strip()]:
            raise ValueError('Rebuilding would change validated source content and undo reviewed fixes. No changes were made; review the saved readings or recapture the file.')
        if final != code:
            parsed = _parse_deterministic(final, store.artifact(new_id))
            apply_structure(store, new_id, parsed['structure'], art['name'], len(final.splitlines()))
            _relink(store)
            with tempfile.TemporaryDirectory() as directory:
                source = Path(directory) / Path(art['name']).name
                source.write_text(final + '\n')
                validation = check_source(source)
            store.set_validation(new_id, validation['tool'], validation['ok'] if validation['checked'] else None,
                                 validation['errors'] if validation['checked'] else validation['note'])
        verification = store.verification(new_id)
        with store.transaction():
            deep = store.get_meta('deepdive') or {}
            deep.pop(str(artifact_id), None)
            store.set_meta('deepdive', deep)
            for key in ('assessment', 'deepdive_program', 'report_stamp', 'ui_flows', 'site_scan'):
                store.set_meta(key, None)
        store.log_run('rebuild_saved_capture', artifact_id=new_id, cost=0, input_tokens=0, output_tokens=0)
        return {'ok': True, 'artifact_id': new_id, 'version': store.artifact(new_id)['version'],
                'frames': len(frames), 'lines': len(code.splitlines()), 'verification': verification,
                'validation': validation, 'api_cost': 0}
