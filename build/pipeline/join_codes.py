"""Join printed licence codes (OCR, 200 dpi pixel space) to the detected boxes
(lon/lat in site/boxes.json) and to the MICI listado tables.

Inputs
  site_build/codes/<date>_<kind>.json   {"file","w","h","codes":[[code,cx,cy],...]}
  site_build/listados.json              {"YYYY-MM|kind": {"source","rows":[...]}}
  site/data_pdf.json                    sheet meta: bounds (lat/lon) + page
  site/boxes.json                       boxes, keyed date|kind, [W,S,E,N]

Outputs
  site/boxcodes.json  {"YYYY-MM|kind": {"<index in boxes.json[date][kind]>": "CODE"}}
  site/license.json   {"YYYY-MM|kind": {"CODE": {company,type,has,status,active}}}

The sheet -> pixel mapping is the inverse of the one used to build the boxes:
  x = (lon - bounds[0][1]) / (bounds[1][1] - bounds[0][1]) * W
  y = (bounds[1][0] - lat) / (bounds[1][0] - bounds[0][0]) * H
with W,H the raster the OCR ran on.  Any render of the page is proportional,
so a codes file may report a 250 dpi native raster instead of the 200 dpi page
box; the boxes are projected into whatever space the file reports.

Assignment is one code per box (a code may label several polygons, and several
labels may share a code) by optimal one-to-one assignment:
  1. cost = distance from the label centre to the box rectangle (0 inside),
     plus a small distance-to-centre term that breaks the tie between the
     nested rectangles that all contain the label;
  2. the caption is printed in the free space beside its polygon, so the
     distance is centred on the rectangle rather than the label size; the cap
     is JOIN_CAP_PX, default 2.2 % of the raster width (~211 px at 100 px/deg
     sheets, i.e. about two label heights);
  3. codes confirmed by the month's listado are placed first so an
     unconfirmed OCR string cannot take a box from a known licence code.
"""
import json, os, re, subprocess, sys
import numpy as np
from scipy.optimize import linear_sum_assignment

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SITE = os.path.join(ROOT, 'site')
BUILD = os.path.join(ROOT, 'site_build')
DPI = 200.0

def load(p, default=None):
    try:
        with open(p) as fh:
            return json.load(fh)
    except Exception:
        return {} if default is None else default

# ---------------------------------------------------------------- raster size
_page_cache = {}

def page_pt(pdf):
    if pdf in _page_cache:
        return _page_cache[pdf]
    out = None
    try:
        txt = subprocess.run(['pdfinfo', pdf], capture_output=True, text=True, timeout=60).stdout
        m = re.search(r'Page size:\s+([\d.]+)\s+x\s+([\d.]+)\s+pts', txt)
        if m:
            out = (float(m.group(1)), float(m.group(2)))
    except Exception:
        pass
    _page_cache[pdf] = out
    return out

_manifest_by_name = {}

def manifest():
    global _manifest_by_name
    if not _manifest_by_name:
        _manifest_by_name = {m['filename']: m for m in
                             load(os.path.join(ROOT, 'manifest_files.json'))}
    return _manifest_by_name

def local_pdf(file):
    """Locate a sheet PDF by file name via manifest_files.json."""
    ent = manifest().get(file)
    if ent and os.path.exists(os.path.join(ROOT, ent['local'])):
        return os.path.join(ROOT, ent['local'])
    return None

def raster_for(rec, cf):
    """Raster (W,H) to express the boxes in.

    The codes file reports the raster it OCR'd, so the boxes are projected into
    that very space (any render of the page is proportional).  The page box at
    200 dpi is the fallback when the codes file is missing or looks like a crop.
    """
    cw, ch = (int(cf.get('w') or 0), int(cf.get('h') or 0)) if cf else (0, 0)
    ref = rec['w'] / float(rec['h']) if rec.get('h') else 0
    if cw > 500 and ch > 500 and ref:
        if abs((cw / ch) / ref - 1) < 0.02:
            return cw, ch
    pt = None
    pdf = local_pdf(rec['file'])
    if pdf:
        pt = page_pt(pdf)
    if pt:
        return round(pt[0] * DPI / 72), round(pt[1] * DPI / 72)
    if cw > 500 and ch > 500:
        return cw, ch
    return int(rec['w']), int(rec['h'])

# ---------------------------------------------------------------- codes
# licence EXP code: 2-4 digit year/sequence + '-' + 1-3 digit number.  On the
# sheets the separator is sometimes printed as '.', ',' or a long dash, and the
# zone suffix may be glued to the code ("93-25Z1").
CODE_RE = re.compile(r'([0-9OILSB]{2,4})[-–—_,.:]([0-9OILSB]{1,3})(?![0-9])')
ZONE_RE = re.compile(r'Z\s*-?\s*(\d{1,2})')
GLYPH = str.maketrans('OILSB', '01158')

def norm_code(raw):
    """'90-07 Z1' -> ('90-07','Z1'); '2005.03' -> ('2005-03'); 'l2-05' -> ('12-05')."""
    t = re.sub(r'\s+', '', (raw or '').upper())
    if not t:
        return None, ''
    m = CODE_RE.search(t)
    if not m:
        return None, ''
    pre, suf = m.group(1).translate(GLYPH), m.group(2).translate(GLYPH)
    if not pre.isdigit() or not suf.isdigit():
        return None, ''
    code = '%s-%s' % (pre, suf.zfill(2) if len(suf) == 1 else suf)
    z = ZONE_RE.search(t[m.end():])
    return code, ('Z' + z.group(1)) if z else ''

def load_codes():
    """All codes files for a sheet, merged.

    A sheet may be OCR'd more than once (codes.py re-runs write
    `<id>_2.json`, ...); the detections are unioned so a re-run adds labels
    instead of replacing the earlier pass.
    """
    d = os.environ.get('CODES_DIR') or os.path.join(BUILD, 'codes')
    out = {}
    if not os.path.isdir(d):
        return out
    for fn in sorted(os.listdir(d)):
        m = re.match(r'^(\d{4}-\d{2})[_-]([a-z]+)[_-]([a-z]+)(?:_\d+)?\.json$', fn)
        if not m:
            m2 = re.match(r'^(\d{4}-\d{2})_(.+?)_codes(?:_\d+)?\.json$', fn)
            if not m2:
                continue
            key = m2.group(1)
            kind = m2.group(2).replace('_', '/', 1)
        else:
            key = m.group(1)
            kind = m.group(2) + '/' + m.group(3)
        cf = load(os.path.join(d, fn))
        if not cf:
            continue
        rec = out.get((key, kind))
        if not rec:
            out[(key, kind)] = cf
            continue
        # a re-run may have used a different raster size: project its codes
        # into the first file's pixel space before merging
        sw = (rec.get('w') or 0) / float(cf.get('w') or 0)
        sh = (rec.get('h') or 0) / float(cf.get('h') or 0)
        codes = cf.get('codes') or []
        if abs(sw - 1) > 0.02 or abs(sh - 1) > 0.02:
            codes = [[c[0], c[1] * sw, c[2] * sh] for c in codes]
        rec['codes'] = (rec.get('codes') or []) + codes
    return out

# ---------------------------------------------------------------- matching
def box_pixels(boxes, bounds, W, H):
    """Box rectangles in sheet pixels: (w0,s0,e0,n0) with the y axis downwards."""
    (s, w), (n, e) = bounds
    sx = W / (e - w)
    sy = H / (n - s)
    out = []
    for i, (w0, s0, e0, n0) in enumerate(boxes):
        out.append(((w0 - w) * sx, (n - n0) * sy, (e0 - w) * sx, (n - s0) * sy, i))
    return out

def rect_dist(pts, idx_p, bpx, idx_b):
    """Distance from each label centre to the box rectangle (0 when inside).

    A licence label is printed in the free space next to its polygon: inside
    the outline when it fits, just outside it otherwise.  Distance to the
    rectangle -- not to its centre -- is therefore the natural cost, and it
    also resolves labels sitting at the edge of a very small polygon.
    """
    X = np.array([[pts[i][1], pts[i][2]] for i in idx_p], float)
    B = np.array([[bpx[j][k] for k in range(4)] for j in idx_b], float)
    dx = np.maximum(np.maximum(B[:, 0] - X[:, 0:1], 0.0), X[:, 0:1] - B[:, 2])
    dy = np.maximum(np.maximum(B[:, 1] - X[:, 1:2], 0.0), X[:, 1:2] - B[:, 3])
    d = np.hypot(dx, dy)
    # a label printed inside a polygon sits near its centre, so the centre
    # distance breaks the tie between the nested/overlapping rectangles that
    # all contain it (cost 0 otherwise, which the assignment resolves blindly)
    dc = np.hypot((B[:, 0] + B[:, 2]) / 2 - X[:, 0:1], (B[:, 1] + B[:, 3]) / 2 - X[:, 1:2])
    return d + 0.1 * dc


def match_assign(pts, bpx, cost_cap, used_c=None, used_b=None):
    """Optimal one-to-one assignment of labels to boxes under `cost_cap` px.

    The Hungarian algorithm is used instead of greedy nearest pairs because
    licence polygons are small and packed: greedy picking lets one label grab
    a box another label belongs to and leaves both codes off the sheet.
    """
    used_c = used_c or set()
    used_b = used_b or set()
    idx_p = [i for i in range(len(pts)) if i not in used_c]
    idx_b = [j for j in range(len(bpx)) if j not in used_b]
    if not idx_p or not idx_b:
        return {}
    D = rect_dist(pts, idx_p, bpx, idx_b)
    C = D.copy()
    C[C > cost_cap] = 1e9
    ri, ci = linear_sum_assignment(C)
    out = {}
    for a, b in zip(ri, ci):
        if C[a, b] >= 1e9:
            continue
        out[idx_b[b]] = idx_p[a]
    return out

# ---------------------------------------------------------------- main
if __name__ == '__main__':
    recs = load(os.path.join(SITE, 'data_pdf.json')) or load(os.path.join(ROOT, 'data_pdf.json'))
    sheets = {(r['date'], r['kind']): r for r in recs}
    boxes = load(os.path.join(SITE, 'boxes.json'))
    codes = load_codes()
    listados = load(os.path.join(BUILD, 'listados.json'))
    if not listados:
        listados = load(os.path.join(SITE, 'listados.json'))

    boxcodes, license_out, report = {}, {}, []

    for (date, kind), cf in sorted(codes.items()):
        rec = sheets.get((date, kind))
        if not rec:
            print('WARN code file for unknown sheet', date, kind, file=sys.stderr)
            continue
        blist = boxes.get(date, {}).get(kind) or []
        if not blist:
            continue
        W, H = raster_for(rec, cf)
        bpx = box_pixels(blist, rec['bounds'], W, H)

        pts, seen = [], set()
        for c in cf.get('codes') or []:
            if len(c) < 3:
                continue
            code, zone = norm_code(c[0])
            if not code:
                continue
            cx, cy = float(c[1]), float(c[2])
            if not (0 <= cx <= W and 0 <= cy <= H):
                continue
            # drop a label that was OCR'd twice in overlapping tiles
            k = (code, round(cx / 40), round(cy / 40))
            if k in seen:
                continue
            seen.add(k)
            pts.append((code, cx, cy))

        # repair is done against the month's listado before matching: a 3-digit
        # prefix is a truncated 4-digit year ("012-01" is "2012-01") and a bare
        # 2-digit prefix may be zero-padded; only accept an unambiguous hit.
        lrow = {}
        for r in (listados.get('%s|%s' % (date, kind), {}).get('rows') or []):
            c0 = norm_code(r.get('code'))[0] or (r.get('code') or '').strip()
            if c0:
                lrow.setdefault(c0, r)
        if lrow:
            fixed = []
            for code, cx, cy in pts:
                if code in lrow:
                    fixed.append((code, cx, cy))
                    continue
                cands = ['2' + code, code.lstrip('0'), code.replace('-', '-0')]
                # a three digit sequence is either a genuine old code ("93-104")
                # or two digits plus the zone glued on ("2013-217" is 2013-21);
                # only the reading that the listado knows is taken
                pre, _, suf = code.partition('-')
                if len(suf) == 3:
                    cands.insert(0, pre + '-' + suf[:2])
                cands = [c for c in cands if c != code and c in lrow]
                fixed.append(((cands[0] if len(set(cands)) == 1 else code), cx, cy))
            pts = fixed

        # a label is printed next to its polygon; cost is the distance from the
        # label centre to the rectangle (0 when it sits inside).  Codes that the
        # listado confirms are placed first so an unconfirmed OCR string cannot
        # take a box away from a known licence code.
        cap = float(os.environ.get('JOIN_CAP_PX', '0')) or 0.022 * W
        conf = set(i for i, p in enumerate(pts) if lrow and p[0] in lrow)
        allc = set(range(len(pts)))
        got, gidx, used_b, used_c = {}, {}, set(), set()
        for group in (conf, allc - conf):
            sub = match_assign(pts, bpx, cap, allc - group | used_c, used_b)
            for bi, ci in sub.items():
                got[bi] = pts[ci][0]
                gidx[bi] = ci
                used_b.add(bi)
                used_c.add(ci)
        inside = 0
        for bi, ci in gidx.items():
            x0, y0, x1, y1, _ = bpx[bi]
            x, y = pts[ci][1], pts[ci][2]
            inside += x0 <= x <= x1 and y0 <= y <= y1

        if got:
            boxcodes.setdefault('%s|%s' % (date, kind), {}).update(
                {str(i): c for i, c in sorted(got.items())})

        hit = sum(1 for c in got.values() if c in lrow)
        occ_hit = len({c for c, _, _ in pts if c in lrow})
        report.append(dict(date=date, kind=kind, boxes=len(blist), codes=len(pts),
                           matched=len(got), in_listado=hit, occ_in_listado=occ_hit,
                           listado_rows=len(lrow), W=W, H=H, inside=inside,
                           cap=round(cap, 1)))

    dropped = 0
    # license.json only needs the sheets that carry codes: the page reads the
    # ficha through the code assigned to a box, so an uncoded sheet never
    # reaches this table.
    for k, v in listados.items():
        if k not in boxcodes:
            continue
        rows = {}
        for r in (v.get('rows') or []):
            code = norm_code(r.get('code'))[0]
            if not code:
                dropped += 1
                continue
            rows.setdefault(code, r)
        if rows:
            license_out[k] = {
                code: {f: r.get(f) for f in ('company', 'type', 'has', 'status', 'active')}
                for code, r in rows.items()
            }

    json.dump(boxcodes, open(os.path.join(SITE, 'boxcodes.json'), 'w'), separators=(',', ':'))
    json.dump(license_out, open(os.path.join(SITE, 'license.json'), 'w'), separators=(',', ':'))
    if dropped:
        print('listado rows with an unusable EXP code: %d' % dropped)

    # per-month report
    agg = {}
    for r in report:
        a = agg.setdefault(r['date'], dict(boxes=0, matched=0, codes=0, in_listado=0,
                                           occ_in_listado=0, listado_rows=0, sheets=0))
        for f in ('boxes', 'matched', 'codes', 'in_listado', 'occ_in_listado', 'listado_rows'):
            a[f] += r[f]
        a['sheets'] += 1
    print('%-8s %5s %5s %6s %5s %6s %7s %7s %8s %7s' % (
        'month', 'sheet', 'boxes', 'codes', 'got', 'box%', 'got/list', 'got/notl',
        'ocr/list', 'listdo'))
    for date in sorted(agg):
        a = agg[date]
        print('%-8s %5d %5d %6d %5d %6.0f%% %7.0f%% %7d %8.0f%% %7d' % (
            date, a['sheets'], a['boxes'], a['codes'], a['matched'],
            100.0 * a['matched'] / max(1, a['boxes']),
            100.0 * a['in_listado'] / max(1, a['matched']),
            a['matched'] - a['in_listado'],
            100.0 * a['occ_in_listado'] / max(1, a['codes']),
            a['listado_rows']))
    tot = dict(boxes=0, matched=0, codes=0, in_listado=0, occ_in_listado=0)
    for a in agg.values():
        for f in tot:
            tot[f] += a[f]
    pdf_boxes = sum(len(v) for c in boxes.values() for v in c.values())
    print('TOTAL boxes %d matched %d (%.0f%%) ocr-codes %d, assigned-codes-in-listado '
          '%d (%.0f%%), ocr-codes-in-listado %d (%.0f%%), sheets %d/%d' % (
              tot['boxes'], tot['matched'], 100.0 * tot['matched'] / max(1, tot['boxes']),
              tot['codes'], tot['in_listado'],
              100.0 * tot['in_listado'] / max(1, tot['matched']),
              tot['occ_in_listado'],
              100.0 * tot['occ_in_listado'] / max(1, tot['codes']),
              len(report), len(sheets)))
    if pdf_boxes > tot['boxes']:
        print('PDF-era boxes in site/boxes.json: %d, covered by a codes file: %d (%.0f%%)'
              % (pdf_boxes, tot['boxes'], 100.0 * tot['boxes'] / pdf_boxes))
    for pct in (30, 40):
        good = [d for d in agg if agg[d]['matched'] >= pct / 100.0 * max(1, agg[d]['boxes'])]
        print('months at >=%d%% of boxes coded: %d of %d months with codes (%s)'
              % (pct, len(good), len(agg), ' '.join(sorted(good))))
    json.dump(dict(per_sheet=report, per_month=agg), open(os.path.join(BUILD, 'join_report.json'), 'w'),
              indent=1)
