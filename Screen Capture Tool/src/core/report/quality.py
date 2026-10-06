"""Version-bound transcription measurements and report evidence qualifications."""
import difflib
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from core.text import normalized_line

COMPARISON_REVISION = '2026-10-01-quoted-spacing-v3'

METHOD = ('Ordered nonblank line matching with whitespace normalized outside quoted literals; '
          'quoted text and spaces inside literals are preserved. Exact layout is measured separately. '
          'Results describe the current reviewed output, including repairs and manual edits, not first-pass OCR accuracy.')
QUALIFICATION = ('This assessment describes the current supplied source. Matching a finding to a transcript does not '
                 'establish source completeness, production reachability, approved business policy or operational effectiveness. '
                 'Ratings and architecture options are provisional until the application boundary, deployed versions and '
                 'business requirements are confirmed. Effort ranges are unvalidated planning scenarios, not a delivery forecast or budget.')
CRITERIA = [
    ('Source fidelity', 'Against known originals, require complete ordered content with no extra or differing lines; preserve quoted literals and validate meaningful fixed columns separately.'),
    ('Stitching and recapture', 'Preserve distinct repeated routines. A complete recapture replaces the selected file version; review progress and errors must reflect that version.'),
    ('Review edits', 'Show the screenshot and adjacent source rows. Retain correction history, recheck corrected text and refresh affected findings.'),
    ('Evidence lifecycle', 'Exclude deleted and superseded files, associated images and stale findings from analysis, diagrams and reports.'),
    ('Report grounding', 'Bind findings and test results to current source hashes. Distinguish observations, architectural interpretation, recommendations and unknowns; scanner zero is not proof of absence.'),
    ('Release validation', 'Resolve source blockers, validate significant layout differences, complete current technical review and obtain agreed technical and business sign-off.'),
]


def source_hash(text):
    return hashlib.sha256((text or '').encode()).hexdigest()


def measure(store, source_pairs):
    """Explicit benchmark inputs only; originals are never copied into captured source."""
    rows = []
    for name, path in source_pairs.items():
        art = store.current_artifact(name)
        if not art:
            continue
        original = Path(path).read_text()
        expected, actual = original.splitlines(), (art.get('transcription') or '').splitlines()
        x = [normalized_line(l) for l in expected if l.strip()]
        y = [normalized_line(l) for l in actual if l.strip()]
        matcher = difflib.SequenceMatcher(None, x, y, autojunk=False)
        matched = sum(b.size for b in matcher.get_matching_blocks())
        rows.append({'artifact': name, 'artifact_id': art['id'], 'version': art.get('version'),
                     'transcription_sha256': source_hash(art.get('transcription')), 'original': Path(path).name,
                     'original_sha256': source_hash(original), 'expected': len(x), 'actual': len(y), 'matched': matched,
                     'expected_layout': len(expected), 'exact_layout': sum(b.size for b in difflib.SequenceMatcher(None, expected, actual, autojunk=False).get_matching_blocks()),
                     'differences': [{'kind': tag, 'expected_line': i+1, 'actual_line': k+1,
                                      'expected': x[i:j], 'actual': y[k:l]} for tag,i,j,k,l in matcher.get_opcodes() if tag != 'equal']})
    result = {'measured_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
              'comparison_revision': COMPARISON_REVISION, 'method': METHOD, 'files': rows}
    store.set_meta('transcription_benchmark', result)
    return result


def current_benchmark(store):
    benchmark = store.get_meta('transcription_benchmark') or {}
    arts = {a['name']: a for a in store.artifacts()}
    rows, stale = [], []
    for row in benchmark.get('files') or []:
        art = arts.get(row['artifact'])
        if not art:  # removed files contribute no text, references or totals
            continue
        if (benchmark.get('comparison_revision') != COMPARISON_REVISION or
                row.get('artifact_id') != art['id'] or row.get('transcription_sha256') != source_hash(art.get('transcription'))):
            stale.append(art['name'])
        else:
            rows.append(row)
    return {**benchmark, 'files': rows, 'stale': stale,
            'unmeasured': sorted(set(arts) - {r['artifact'] for r in rows} - set(stale))}


def summary(store):
    from core import deepdive
    benchmark = current_benchmark(store)
    arts = store.artifacts()
    source = [a for a in arts if a.get('artifact_type') not in ('ui_screen', 'document')]
    reviewed = deepdive.current_reviews(store)
    blockers = [r['name'] + ': ' + '; '.join(deepdive.report_reason(i) for i in r['issues'])
                for r in deepdive.rescan_requests(store)]
    blockers += [a['name'] + ': current technical review pending' for a in source if str(a['id']) not in reviewed]
    blockers += [name + ': transcription benchmark needs refresh' for name in benchmark['stale']]
    source_names = {a['name'] for a in source}
    unmeasured = [name for name in benchmark['unmeasured'] if name in source_names]
    if unmeasured:
        blockers.append(f"{len(unmeasured)} source file{'s' if len(unmeasured) != 1 else ''} ({', '.join(unmeasured)}): source completeness remains unconfirmed "
                        "(no current original-file benchmark)")
    blockers += [r['artifact'] + ': original-file content differs' for r in benchmark['files']
                 if r['expected'] != r['matched'] or r['actual'] != r['matched']]
    layout = store.get_meta('source_layout_validation') or {}
    by_name = {a['name']: a for a in arts}
    from core.cobol import is_column_sensitive
    from core.langpacks.formats import detect_format
    for row in benchmark['files']:
        art = by_name[row['artifact']]
        text = art.get('transcription') or ''
        sensitive = is_column_sensitive(text) or detect_format(text, art.get('language') or '', Path(art['name']).suffix) in ('asm', 'rpg_fixed', 'fortran', 'pli')
        accepted = layout.get(art['name']) or {}
        if sensitive and row['exact_layout'] != row['expected_layout'] and not (
                accepted.get('confirmed') is True and accepted.get('transcription_sha256') == source_hash(text)):
            blockers.append(art['name'] + ': meaningful column layout requires separate validation')
    return {'benchmark': benchmark, 'blockers': blockers, 'qualification': QUALIFICATION}


def blocks(store):
    q = summary(store)
    b = q['benchmark']
    result = [{'type': 'p', 'text': QUALIFICATION}, {'type': 'h', 'text': 'Transcription validation'},
              {'type': 'p', 'text': METHOD}]
    if b['files']:
        expected = sum(r['expected'] for r in b['files']); actual = sum(r['actual'] for r in b['files']); matched = sum(r['matched'] for r in b['files'])
        result += [{'type': 'p', 'text': f"Measured {b.get('measured_at', '')[:10]}: {matched:,} of {expected:,} original nonblank lines match the {actual:,} transcribed lines. Content recall {100*matched/max(1,expected):.4f}%; precision {100*matched/max(1,actual):.4f}%. Exact layout differences require separate assessment; normalized content agreement does not establish column fidelity."},
                   {'type': 'table', 'head': ['Artifact', 'Original', 'Captured', 'Matched'],
                    'rows': [[r['artifact'], str(r['expected']), str(r['actual']), str(r['matched'])] for r in b['files']]}]
        exact = sum(r['exact_layout'] for r in b['files']); all_lines = sum(r['expected_layout'] for r in b['files'])
        result.append({'type': 'p', 'text': f'Exact layout: {exact:,} of {all_lines:,} source rows match ({100*exact/max(1,all_lines):.4f}%). Differences include spacing and are not all syntax defects. Fixed-column acceptance remains a separate reviewer decision.'})
    else:
        result.append({'type': 'p', 'text': 'No current original-file benchmark was supplied. Source completeness is unconfirmed; capture checks and compilation do not establish it.'})
    if b['stale'] or b['unmeasured']:
        result.append({'type': 'p', 'text': 'Benchmark coverage remains incomplete. Stale or unmeasured results are excluded from the totals.'})
    if q['blockers']:
        result += [{'type': 'h', 'text': 'Open source validation items'}, {'type': 'bullets', 'items': q['blockers']}]
    result += [{'type': 'h', 'text': 'Proposed software acceptance criteria'},
               {'type': 'p', 'text': 'These criteria are proposed engineering improvements; organizational approval and production acceptance remain to confirm.'},
               {'type': 'table', 'head': ['Area', 'Criterion'], 'rows': [list(c) for c in CRITERIA]}]
    return result
