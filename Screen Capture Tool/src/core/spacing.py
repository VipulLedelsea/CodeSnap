"""Image-bound spacing evidence. OCR agreement never establishes column one."""
import difflib
import hashlib
import io
import json
import math
import tempfile
from contextlib import contextmanager
from pathlib import Path

from PIL import Image
from core import colfix

REVISION = 'spacing-v2'


def image_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def profile(data, region, origin):
    """The user selected the source pane and clicked its visible column one."""
    if isinstance(origin, bool) or not isinstance(origin, (int, float)) or not math.isfinite(origin) or not 0 <= origin <= 1:
        raise ValueError('Click the first source column inside the selected area.')
    image = Image.open(io.BytesIO(data)).convert('RGB')
    w,h = image.size
    l,t,r,b = round(region[0]*w), round(region[1]*h), round((region[0]+region[2])*w), round((region[1]+region[3])*h)
    crop = image.crop((l,t,r,b))
    with tempfile.TemporaryDirectory() as directory:
        p = Path(directory)/'source.png'; crop.save(p)
        fit,pitch,_ = colfix._grid(colfix._rows(colfix._ink(p)))
    if pitch is None or fit < colfix.MIN_GRID_FIT:
        raise ValueError('Spacing cannot be measured here. Select only the source pane, with a fixed-width font.')
    return {'reviewed':True, 'origin':float(origin), 'size':list(crop.size), 'pitch':pitch,
            'reference_sha256':hashlib.sha256(data).hexdigest()}


def validate_profile(value):
    if not isinstance(value, dict) or value.get('reviewed') is not True:
        raise ValueError('Confirm the source margin before using spacing calibration.')
    origin, pitch, size = value.get('origin'),value.get('pitch'),value.get('size')
    if (isinstance(origin,bool) or not isinstance(origin,(int,float)) or not math.isfinite(origin) or not 0 <= origin <= 1
            or isinstance(pitch,bool) or not isinstance(pitch,(int,float)) or not math.isfinite(pitch) or not 4 <= pitch <= 32
            or not isinstance(size,list) or len(size)!=2 or any(type(n) is not int or n<=0 for n in size)
            or not isinstance(value.get('reference_sha256'),str) or len(value['reference_sha256'])!=64):
        raise ValueError('The saved source margin is invalid. Select the code area again.')
    return {k:value[k] for k in ('reviewed','origin','size','pitch','reference_sha256')}


def bind(path, calibration):
    """Retain a frame-specific result; changed scale/font/layout requires review."""
    record={'revision':REVISION,'image_sha256':image_hash(path),'confirmed':False}
    if calibration:
        try:
            calibration=validate_profile(calibration)
            with Image.open(path) as image: w,h=image.size
            ratio=w/calibration['size'][0]
            fit,pitch,phase=colfix._grid(colfix._rows(colfix._ink(path)))
            if (abs(h/calibration['size'][1]-ratio)>0.025*ratio or pitch is None or fit<colfix.MIN_GRID_FIT
                    or abs(pitch-calibration['pitch']*ratio)>0.04*pitch):
                raise ValueError('The capture size or font changed. Set the source margin again.')
            source_x=calibration['origin']*w
            # a click lands anywhere inside a character cell; the column edge is the nearest grid line
            cell=source_x/pitch-phase
            source_x=(round(cell)+phase)*pitch
            record.update(confirmed=True,size=[w,h],source_x=source_x,box=[0,0,w,h],pitch=pitch,
                          reference_sha256=calibration['reference_sha256'])
        except (ValueError,KeyError,TypeError) as exc:
            record['reason']=str(exc)
    else:
        record['reason']='Source margin has not been confirmed.'
    Path(path).with_suffix('.spacing.json').write_text(json.dumps(record))
    return record


def calibration_for(path):
    try:
        value=json.loads(Path(path).with_suffix('.spacing.json').read_text())
        return value if isinstance(value,dict) else {}
    except (OSError,ValueError):
        return {}


@contextmanager
def frame(path, calibration=None):
    """Yield the image and independent origin only when bound to these bytes."""
    value=calibration if calibration is not None else calibration_for(path)
    value=value if isinstance(value,dict) else {}
    evidence={'revision':REVISION,'image_sha256':image_hash(path),'calibrated':False,
              'reason':value.get('reason','Source margin has not been confirmed.')}
    try:
        image=Image.open(path)
    except OSError:
        evidence['reason']='Screenshot cannot be measured.'
        yield Path(path),None,evidence
        return
    with image:
        w,h=image.size
        box=value.get('box',[0,0,w,h]); x=value.get('source_x')
        valid=(value.get('confirmed') is True and value.get('image_sha256')==evidence['image_sha256']
               and value.get('size')==[w,h] and isinstance(box,list) and len(box)==4
               and all(type(n) is int for n in box) and 0<=box[0]<box[2]<=w and 0<=box[1]<box[3]<=h
               and type(x) in (int,float) and math.isfinite(x) and box[0]<=x<box[2])
        if not valid:
            yield Path(path),None,evidence
            return
        with tempfile.TemporaryDirectory() as directory:
            cropped=Path(directory)/'source.png'; image.crop(tuple(box)).save(cropped)
            evidence.update(calibrated=True,reason='',calibration=value)
            yield cropped,x-box[0],evidence


def signature(calibration):
    return hashlib.sha256(json.dumps(calibration or {},sort_keys=True).encode()).hexdigest()


def positions(source,reading):
    """Unique surrounding rows identify repeated statements without guessing.

    For each row of the reading, the source position is the one place where the row and the rows around it (two to twelve on each
    side) all agree. Only places where the row itself occurs can match, so the search starts from an index of the source and
    widens the window over the places still standing, instead of comparing the window with every position of the source."""
    from core.text import normalized_line
    keys=[normalized_line(s) for s in source]
    other=[normalized_line(s) for s in reading]
    where={}
    for i,k in enumerate(keys):
        where.setdefault(k,[]).append(i)
    n=len(keys); matches={}
    for j in range(len(other)):
        if not other[j] or '[CUT OFF]' in reading[j]:
            continue
        cand=None; lo_done=hi_done=None
        for radius in range(2,13):
            lo,hi=max(0,j-radius),min(len(other),j+radius+1)
            if hi-lo<3:
                continue
            if cand is None:
                cand=[i for i in where.get(other[j],()) if i-(j-lo)>=0 and i+(hi-j)<=n
                      and keys[i-(j-lo):i+(hi-j)]==other[lo:hi]]
            else:
                cand=[i for i in cand if i-(j-lo)>=0 and i+(hi-j)<=n
                      and all(keys[i-(j-t)]==other[t] for t in range(lo,lo_done))
                      and all(keys[i+(t-j)]==other[t] for t in range(hi_done,hi))]
            lo_done,hi_done=lo,hi
            if len(cand)==1:
                matches[j]=cand[0]
                break
    return matches


def _pick_lead(pixel):
    """The leading column the pixel readings of one line settle on: the only value when they all agree; with disagreement, the
    value most screenshots give when at least two do and it has twice the votes of any other (a row paired with the wrong line
    or an edge row is then the odd one out). None when there is no such value."""
    if not pixel:
        return None
    votes=sorted(((pixel.count(v),v) for v in set(pixel)),reverse=True)
    if len(votes)==1:
        return votes[0][1]
    top,second=votes[0][0],votes[1][0]
    return votes[0][1] if top>=2 and top>=2*second else None


def _corroborated(pixel,model):
    """A pixel-read leading column is trusted when two screenshots give it, or when the one that gives it sits within a column
    of what the readers wrote. One row on one screenshot can be paired with the wrong line or carry a leftover mark at the
    margin; against every reader's value that is not evidence."""
    if len(pixel)>=2:
        return True
    if not model:
        return True
    common=max(set(model),key=model.count)
    return abs(pixel[0]-common)<=1 or model.count(common)<2


def _squeeze_dashes(text):
    import re
    return re.sub(r'[-\u2500-\u257f\u2013\u2014=]+','-',text)


def _same_line_shape(a,b):
    """Do two reads of one row look like the same line? Separator comments are read with a different number or kind of dashes
    on each screenshot ('# -- Core ----' against '# ── Core ──────'), so dash runs count as one mark before comparing."""
    return difflib.SequenceMatcher(None,_squeeze_dashes(a.strip()),_squeeze_dashes(b.strip())).ratio()>=0.7


def reconcile(code,parts,metas):
    """Prefer positioned measured columns; retain unresolved disagreements."""
    from collections import defaultdict
    from core.text import literal_continuations
    lines=code.split('\n'); protected=literal_continuations(code)
    votes,seen=defaultdict(set),defaultdict(set)
    active=False
    for part,meta in zip(parts,metas):
        rows=part.split('\n'); evidence=(meta or {}).get('spacing') or {}
        active=active or bool(evidence)
        states=evidence.get('line_status') or []
        for j,i in positions(lines,rows).items():
            if i in protected or '[CUT OFF]' in lines[i] or '\t' in lines[i]:
                continue
            seen[i].add(rows[j])
            if evidence.get('calibrated') is True and j<len(states) and states[j]=='measured':
                votes[i].add(rows[j])
    from core.verify import _line_map, _norm
    for part,meta in zip(parts,metas):
        evidence=(meta or {}).get('spacing') or {}
        states=evidence.get('line_status') or []
        if evidence.get('calibrated') is not True:
            continue
        rows=part.split('\n')
        for i,j in enumerate(_line_map(part,code)):
            if (j is None or j>=len(states) or states[j]!='measured' or i in protected or '[CUT OFF]' in lines[i]
                    or '\t' in lines[i] or not lines[i].strip()):
                continue
            if _norm(lines[i])==_norm(rows[j]):
                seen[i].add(rows[j]); votes[i].add(rows[j])
    # leading columns read from the pixels place a line even when its words were misread on some screenshots
    from core.verify import _line_map, _norm
    leadvotes=defaultdict(set); pixel_all=defaultdict(list); model_all=defaultdict(list)
    squeezed_code=_squeeze_dashes(code)
    for part,meta in zip(parts,metas):
        evidence=(meta or {}).get('spacing') or {}
        placed=evidence.get('lead_px') or []
        rows=part.split('\n')
        if evidence.get('calibrated') is not True or len(placed)!=len(rows):
            continue
        for i,j in enumerate(_line_map(_squeeze_dashes(part),squeezed_code,carry_replacements=True)):
            if (j is None or placed[j] is None or '[CUT OFF]' in lines[i] or '\t' in lines[i]
                    or not lines[i].strip() or not rows[j].strip()):
                continue
            if (_norm(lines[i])!=_norm(rows[j]) and _same_line_shape(lines[i],rows[j]) is False):
                continue                              # a different line: the same row position does not make it the same line
            leadvotes[i].add(placed[j]); seen[i].add(rows[j])
            pixel_all[i].append(placed[j]); model_all[i].append(len(rows[j])-len(rows[j].lstrip()))
    status=['' if not line.strip() else 'unmeasured' for line in lines]
    conflicts=[]
    for i,readings in seen.items():
        measured=votes[i]
        pick=_pick_lead(pixel_all.get(i,[]))
        if pick is not None and not _corroborated(pixel_all[i],model_all[i]):
            conflicts.append(i+1); status[i]='conflict'
        elif pick is not None:
            # the pixels gave one leading column on every screenshot that shows this line: its spacing is settled whatever
            # the words were read as. The line counts as measured only when the screenshots also agree on its words.
            same=len({_norm(r) for r in readings})==1
            words=next(iter(measured)) if len(measured)==1 and same else lines[i]
            lines[i]=' '*pick+words.lstrip(); status[i]='measured' if same and len(leadvotes[i])==1 else 'unmeasured'
        elif len(measured)==1:
            lines[i]=next(iter(measured)); status[i]='measured'
        elif len(measured)>1 or len(readings)>1:
            conflicts.append(i+1); status[i]='conflict'
        elif active:
            status[i]='unmeasured'
    shifted={}
    for part,meta in zip(parts,metas):
        if ((meta or {}).get('spacing') or {}).get('calibrated') is True:
            continue
        rows=part.split('\n'); mapping=_line_map(part,code)
        pairs=[(i,j) for i,j in enumerate(mapping) if j is not None and lines[i].strip() and _norm(lines[i])==_norm(rows[j])
               and i not in protected and '[CUT OFF]' not in lines[i] and '\t' not in lines[i]]
        deltas=[len(lines[i])-len(lines[i].lstrip())-(len(rows[j])-len(rows[j].lstrip())) for i,j in pairs if status[i]=='measured']
        if len(deltas)<3:
            continue
        d=max(set(deltas),key=deltas.count)
        if d==0 or deltas.count(d)<0.8*len(deltas):
            continue
        for i,j in pairs:
            if status[i]=='measured':
                continue
            lead=len(rows[j])-len(rows[j].lstrip())+d
            if lead<0:
                continue
            new=' '*lead+rows[j].lstrip()
            if shifted.get(i,new)!=new:
                conflicts.append(i+1); status[i]='conflict'; continue
            shifted[i]=new
    for i,new in shifted.items():
        if status[i]!='conflict':
            lines[i]=new; status[i]='measured'
    return '\n'.join(lines), {'spacing_statuses':status,'spacing_conflicts':conflicts} if active else {'spacing_conflicts':conflicts}


INDICATOR_INDEX = 6


def anchored_origin(path, raw):
    """Source column one, in pixels, from the screenshot alone. In fixed-format COBOL a comment's '*' always sits in
    column 7, so every comment row says where column one is. Returns None unless every comment row agrees."""
    try:
        m = colfix._measure(path, raw.replace('[CUT OFF]', ''))
    except Exception:
        return None
    if not m:
        return None
    votes = {}
    for ri, li in m['pairs']:
        t = m['plain'][li].lstrip()
        if t.startswith('*') and not t.startswith('*>') and m['measured'][ri]:
            d = INDICATOR_INDEX - m['measured'][ri][0][0]
            votes[d] = votes.get(d, 0) + 1
    if not votes:
        return None
    base = max(votes, key=votes.get)
    if votes[base] < 0.8 * sum(votes.values()):
        return None
    x = (m['offset'] - base) * m['pitch']
    return float(x) if 0 <= x < Image.open(path).size[0] else None
