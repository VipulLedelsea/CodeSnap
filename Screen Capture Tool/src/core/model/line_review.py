"""Local screenshot questions for uncertain source lines. No generated source or API calls."""
import re
from pathlib import Path

from PIL import Image
from core import colfix, deepdive
from core.analysis import clean_source, source_mode, _normalize_extract, _SOURCE_LABEL
from core.verify import _line_map


def items(store, art):
    lines = (art.get('transcription') or '').splitlines()
    flags = (store.verification(art['id']) or {}).get('flags') or []
    concerns = deepdive.current_concerns(store, art) or []
    by_line = {}
    for flag in [*flags, *concerns]:
        n = flag.get('line')
        if isinstance(n, int) and 0 < n <= len(lines):
            by_line.setdefault(n, []).append(flag.get('reason') or 'Text needs review')
    if art.get('validation_ok') == 0:
        for n in re.findall(r'(?:line|:)\s*(\d{1,5})\b', art.get('validation_errors') or ''):
            n = int(n)
            if 0 < n <= len(lines):
                by_line.setdefault(n, []).append('Source check reports an error here; confirm what the screenshot actually says.')
    return [{'line': n, 'text': lines[n - 1], 'reasons': list(dict.fromkeys(reasons))}
            for n, reasons in sorted(by_line.items())]


def _locate(code, clean, line):
    """Require a unique multi-row context; repeated statements alone cannot identify a frame."""
    final, frame = code.splitlines(), clean.splitlines()
    positions = {}
    for idx, text in enumerate(final):
        positions.setdefault(text.strip(), []).append(idx)
    mapping = _line_map(code, clean, carry_replacements=True)
    found = []
    for ri, fi in enumerate(mapping):
        if fi != line - 1:
            continue
        lo, hi = max(0, ri - 3), min(len(frame), ri + 4)
        nearby = [(j, mapping[j]) for j in range(lo, hi) if mapping[j] is not None]
        # At least two neighbouring exact nonblank lines establish the position.
        neighbours = [(j, f) for j, f in nearby if j != ri and frame[j].strip() and
                      frame[j].strip() == final[f].strip() and f - fi == j - ri]
        if len(neighbours) < 2:
            continue
        offsets = [(j-ri, frame[j].strip()) for j, _ in neighbours]
        first_offset, first_text = offsets[0]
        candidates = (idx-first_offset for idx in positions.get(first_text, []))
        possible = [idx for idx in candidates if all(0 <= idx+off < len(final) and
                    final[idx+off].strip() == text for off, text in offsets)]
        if possible != [fi]:
            # Include the owning paragraph where local repeated boilerplate is ambiguous.
            anchor = next((j for j in range(ri, -1, -1)
                           if _SOURCE_LABEL.fullmatch(frame[j].strip())), None)
            if anchor is None or mapping[anchor] is None:
                continue
            expected = fi - (ri-anchor)
            if mapping[anchor] != expected or final[expected].strip() != frame[anchor].strip():
                continue
            if len(positions.get(frame[anchor].strip(), [])) != 1:
                continue
        found.append((len(neighbours), ri))
    return max(found)[1] if found else None


def _band(path, raw, index):
    """Locate the row from measured pixels, never from an assumed equal row spacing."""
    from core.spacing import frame
    with frame(path) as (image,origin,evidence):
        measurement = colfix._measure(image,raw.replace('[CUT OFF]',''),source_x=origin) if origin is not None else colfix._measure(image,raw.replace('[CUT OFF]',''))
    y_offset=(evidence.get('calibration') or {}).get('box',[0,0,0,0])[1]
    if not measurement:
        return None
    body_index = next((i for i, (raw_i, _) in enumerate(measurement['body']) if raw_i == index), None)
    if body_index is None:
        return None
    pairs = measurement['pairs']
    row = next((r for r, l in pairs if l == body_index), None)
    if row is None:
        for (r0, l0), (r1, l1) in zip(pairs, pairs[1:]):
            if l0 < body_index < l1 and r1-r0 == l1-l0:
                row = r0 + body_index-l0
                break
    if row is None:
        return None
    return [y+y_offset for y in measurement['bands'][row]]


def question(text, readings):
    current = text.split()
    for reading in readings:
        other = reading.split()
        if len(current) != len(other):
            continue
        differences = [(a,b) for a,b in zip(current, other) if a != b]
        if len(differences) == 1:
            a,b = differences[0]
            a0,b0 = a.rstrip('.,;'),b.rstrip('.,;')
            if re.fullmatch(r'\d+(?:\.\d+)?', a0) and re.fullmatch(r'\d+(?:\.\d+)?', b0):
                if a0 == b0+'0' or b0 == a0+'0':
                    return f'Is there a trailing zero here: {a0} or {b0}? Select the complete line you see below.'
                return f'Which number does the highlighted line show: {a0} or {b0}?'
    return 'Does the highlighted line match the text below? Confirm it or enter the complete correct line.'


def detail(store, art, line):
    code = art.get('transcription') or ''
    lines = code.splitlines()
    if line < 1 or line > len(lines):
        raise ValueError('This line is outside the current file.')
    screenshots, readings = [], []
    for evidence in store.artifact_evidence(art['id']):
        cache = store.text_cache_dir / (evidence['sha256']+'.md')
        if not cache.exists():
            continue
        raw = cache.read_text()
        if '"raw_transcription"' in raw:
            try:
                raw = _normalize_extract(raw)['raw']
            except ValueError:
                continue
        clean = clean_source(raw, source_mode([raw]))
        index = _locate(code, clean, line)
        if index is None:
            continue
        raw_map = _line_map(raw, clean, carry_replacements=True)
        raw_index = raw_map[index] if index < len(raw_map) else None
        if raw_index is None:
            continue
        path = Path(store.evidence(evidence['id'])['abs_path'])
        if not path.exists():
            continue
        band = _band(path, raw, raw_index)
        with Image.open(path) as image:
            width, height = image.size
        observed = clean.splitlines()[index]
        if observed not in readings:
            readings.append(observed)
        screenshots.append({'id': evidence['id'], 'frame': evidence['ord']+1, 'width': width, 'height': height,
                            'band': band, 'text': observed})
    screenshots.sort(key=lambda e: e['band'] is None)
    return {'artifact_id': art['id'], 'name': art['name'], 'line': line, 'old_text': lines[line-1],
            'text_hash': deepdive._hash(code), 'question': question(lines[line-1], readings),
            'context': [{'line': n, 'text': lines[n-1], 'focus': n == line}
                        for n in range(max(1, line-1), min(len(lines), line+1)+1)],
            'screenshots': screenshots[:6], 'readings': readings,
            'reasons': next((i['reasons'] for i in items(store, art) if i['line'] == line), [])}
