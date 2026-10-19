"""Lines the user has looked at and accepted stay accepted, whatever later rebuild or recapture produces the file."""


def _norm(s):
    return ' '.join((s or '').replace('[CUT OFF]', '').split())


def signature(lines, n):
    return [_norm(lines[n - 1]), _norm(lines[n - 2]) if n > 1 else '', _norm(lines[n]) if n < len(lines) else '']


def add(store, name, text, n):
    lines = (text or '').splitlines()
    if not 0 < n <= len(lines):
        return
    allc = store.get_meta('confirmed_lines') or {}
    sigs = allc.setdefault(name, [])
    sig = signature(lines, n)
    if sig not in sigs:
        sigs.append(sig)
    store.set_meta('confirmed_lines', allc)


def is_confirmed(sigs, lines, n):
    if not sigs or not 0 < n <= len(lines):
        return False
    here, prev, nxt = signature(lines, n)
    if not here:
        return False
    unique = sum(1 for l in lines if _norm(l) == here) == 1
    for s_here, s_prev, s_next in sigs:
        if s_here == here and (unique or s_prev == prev or s_next == nxt):
            return True
    return False


def keep_unconfirmed(store, name, text, flags):
    sigs = (store.get_meta('confirmed_lines') or {}).get(name)
    if not sigs or not flags:
        return flags
    lines = (text or '').splitlines()
    return [f for f in flags if not (isinstance(f.get('line'), int) and is_confirmed(sigs, lines, f['line']))]


def remove(store, name, text, n):
    lines = (text or '').splitlines()
    if not 0 < n <= len(lines):
        return
    allc = store.get_meta('confirmed_lines') or {}
    sig = signature(lines, n)
    allc[name] = [s for s in allc.get(name, []) if s != sig]
    store.set_meta('confirmed_lines', allc)


def mark_missing(store, name, text, n):
    lines = (text or '').splitlines()
    if not 0 < n <= len(lines):
        return
    allm = store.get_meta('missing_marks') or {}
    sigs = allm.setdefault(name, [])
    sig = signature(lines, n)
    if sig not in sigs:
        sigs.append(sig)
    store.set_meta('missing_marks', allm)


def is_marked_missing(store, name, text, n):
    sigs = (store.get_meta('missing_marks') or {}).get(name)
    return is_confirmed(sigs, (text or '').splitlines(), n)


# ── structural findings that belong to the whole file, not to a line ─────────────────────────────────────────────────────────────

def _hash(text):
    import hashlib
    return hashlib.sha256((text or '').encode()).hexdigest()


def accept_reasons(store, art, reasons):
    """The person accepted these whole-file findings ("paragraph 5120 is missing", "unclosed brace") as they are. Valid for this exact
    text of this version of the file only."""
    allr = store.get_meta('accepted_reasons') or {}
    key, digest = str(art['id']), _hash(art.get('transcription'))
    have = set(allr.get(key, {}).get('reasons', [])) if allr.get(key, {}).get('hash') == digest else set()
    allr[key] = {'hash': digest, 'reasons': sorted(have | set(reasons))}
    store.set_meta('accepted_reasons', allr)


def accepted_reasons(store, art):
    entry = (store.get_meta('accepted_reasons') or {}).get(str(art['id'])) or {}
    return set(entry.get('reasons') or []) if entry.get('hash') == _hash(art.get('transcription')) else set()
