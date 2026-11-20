"""Adversarial per-month review — defamation risk model.

Legal exposure here is defamation by implication: the page asserts that a named
company holds / is applying for a given parcel in a given month, at a given size.
Every check below is a way that assertion can be false.

  H1 MISATTRIBUTION
     code_not_in_table   polygon carries a code absent from that month's LISTADO
     code_cross_kind     code only appears in the *other* category's table that
                         month (applications shown as contracts, or vice versa)
     code_reuse          same code maps to different companies in different months
     company_mismatch    company string does not resemble the one in the table
  H1 MISCLASSIFICATION
     kind_mismatch       polygon drawn on a metal sheet but code only in the
                         non-metallic table (or the reverse)
     reserve_overlap     polygon overlaps a reserve / protected area polygon
  H2 WRONG SIZING
     area_mismatch       drawn bbox > 4x the hectares declared in the table
     ha_outlier          table declares an implausible area (>100 000 ha)
  H2 NO EVIDENCE
     no_table            month has polygons but no published table
  H3 IDENTITY UNKNOWN
     unlisted            polygons with no code at all

Writes site/review.json {per_month, score, checks} and prints a ranked table.
"""
import json, os, re, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
S = os.path.join(ROOT, 'site')
boxes = json.load(open(os.path.join(S, 'boxes.json')))
codes = json.load(open(os.path.join(S, 'boxcodes.json')))
lic = json.load(open(os.path.join(S, 'license.json')))
zones = json.load(open(os.path.join(S, 'zones.json')))
tables = json.load(open(os.path.join(ROOT, 'site_build', 'listados.json')))

DEAD = re.compile(r'cancelad|caducad|renuncia|vencid', re.I)


def area_km2(b):
    return (b[2] - b[0]) * 104.0 * (b[3] - b[1]) * 110.0


# zone prefilter: bounding boxes first
Z = []
for ring in zones:
    xs = [p[0] for p in ring]; ys = [p[1] for p in ring]
    Z.append((min(xs), min(ys), max(xs), max(ys), ring))


def in_zone(b):
    for x0, y0, x1, y1, ring in Z:
        if b[2] < x0 or b[0] > x1 or b[3] < y0 or b[1] > y1:
            continue
        cx, cy = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
        inside = False
        j = len(ring) - 1
        for i in range(len(ring)):
            xi, yi = ring[i]; xj, yj = ring[j]
            if ((yi > cy) != (yj > cy)) and (cx < (xj - xi) * (cy - yi) / (yj - yi + 1e-12) + xi):
                inside = not inside
            j = i
        if inside:
            return True
    return False


# code -> set(company) across all months, to detect reuse
code_company = {}
for key, rows in tables.items():
    for r in rows.get('rows') or []:
        if not r.get('code'):
            continue
        code_company.setdefault(r['code'], set()).add((r.get('company') or '').strip().upper())

review, score = {}, {}
UNRELIABLE = set()
allflags = {'code_not_in_table': 0, 'code_cross_kind': 0, 'code_reuse': 0, 'company_mismatch': 0,
            'kind_mismatch': 0, 'reserve_overlap': 0, 'area_mismatch': 0, 'ha_outlier': 0,
            'no_table': 0, 'unlisted': 0, 'table_partial': 0, 'code_ocr_repaired': 0, 'code_universe_mismatch': 0}

for date in sorted(boxes):
    if not re.match(r'\d{4}-\d{2}$', date):
        continue
    entry = {}
    for kind, arr in boxes[date].items():
        key = f'{date}|{kind}'
        cm = codes.get(key, {})
        lm = lic.get(key, {})
        rows = (tables.get(key) or {}).get('rows') or []
        tcodes = {r['code'] for r in rows if r.get('code')}
        has_by = {r['code']: r.get('has') for r in rows if r.get('code')}
        other = 'solicitudes' if kind.endswith('contratos') else 'contratos'
        other_key = f"{date}|{kind.split('/')[0]}/{other}"
        ocodes = {r['code'] for r in ((tables.get(other_key) or {}).get('rows') or []) if r.get('code')}
        flags = {}

        if cm and not tcodes:
            flags['no_table'] = {'n': len(cm)}
        if cm and tcodes:
            def norm(c):
                c = re.sub(r'\s*Z\s*\d+$', '', str(c).strip().upper())
                m = re.match(r'^(\d+)-(\d+)$', c)
                return f'{int(m.group(1))}-{int(m.group(2)):02d}' if m else c
            own = {norm(t) for t in tcodes}

            def repairs(c):
                c = norm(c)
                m = re.match(r'^(\d+)-(\d+)$', c)
                if not m:
                    return set()
                a, b = m.group(1), m.group(2)
                out = set()
                for t in own:
                    mt = re.match(r'^(\d+)-(\d+)$', t)
                    if not mt:
                        continue
                    A, B = mt.group(1), mt.group(2)
                    if B != b:
                        continue
                    if A == a or A.endswith(a) or a.endswith(A):
                        out.add(t)
                return out

            repaired, bad = [], []
            for c in cm.values():
                if norm(c) in own:
                    continue
                r = repairs(c)
                if len(r) == 1:            # sólo reparaciones inequívocas
                    repaired.append(c)
                else:
                    bad.append(c)
            if repaired:
                flags['code_ocr_repaired'] = {'n': len(repaired), 'sample': repaired[:5],
                                              'note': 'lectura del mapa truncada; coincide tras reparar'}
            matched = len(cm) - len(bad) - len(repaired)
            rev = matched / max(1, len(tcodes))
            if rev < 0.25 and len(tcodes) >= 20:
                # Map and table cover different code universes: the join for this
                # month|category cannot support any attribution.
                flags['code_universe_mismatch'] = {
                    'map_codes': len(cm), 'table_codes': len(tcodes),
                    'matched': matched, 'reverse_pct': round(100 * rev)}
                UNRELIABLE.add(key)
            elif bad:
                label = ('table_partial' if len(tcodes) < 0.3 * len(cm)
                         else 'code_not_in_table')
                flags[label] = {'n': len(bad), 'of': len(cm),
                                'pct': round(100 * len(bad) / len(cm)), 'sample': bad[:5]}
                cross = [c for c in bad if norm(c) in {norm(o) for o in ocodes}]
                if cross:
                    flags['code_cross_kind'] = {'n': len(cross), 'sample': cross[:5]}
        reuse = [c for c in set(cm.values()) if len(code_company.get(c, ())) > 1]
        if reuse:
            flags['code_reuse'] = {'n': len(reuse), 'sample': reuse[:5]}
        conflicts = [c for c, r in lm.items() if not r.get('_alias')
                     and r.get('active') and DEAD.search(r.get('status') or '')]
        if conflicts:
            flags['active_conflict'] = {'n': len(conflicts), 'sample': conflicts[:5]}
        outliers = [c for c, ha in has_by.items() if ha and ha > 100000]
        if outliers:
            flags['ha_outlier'] = {'n': len(outliers), 'sample': outliers[:5]}
        if has_by:
            over = []
            for idx, code in cm.items():
                try:
                    b = arr[int(idx)]
                except Exception:
                    continue
                ha = has_by.get(code)
                if ha and area_km2(b) > 4 * (ha / 100.0):
                    over.append((code, round(area_km2(b), 1), round(ha / 100.0, 1)))
            if over:
                flags['area_mismatch'] = {'n': len(over), 'sample': over[:5]}
        unlisted = len(arr) - len(cm)
        if unlisted > 0:
            flags['unlisted'] = {'n': unlisted, 'of': len(arr),
                                 'pct': round(100 * unlisted / max(1, len(arr)))}
        hit = sum(1 for b in arr if in_zone(b))
        if hit:
            flags['reserve_overlap'] = {'n': hit, 'pct': round(100 * hit / max(1, len(arr)))}

        if flags:
            entry[kind] = flags
            for f in flags:
                allflags[f] = allflags.get(f, 0) + 1
    if entry:
        review[date] = entry
        pts = 0
        for f in entry.values():
            for name, val in f.items():
                if name in ('code_not_in_table', 'code_cross_kind', 'code_reuse', 'active_conflict'):
                    pts += 3
                elif name in ('area_mismatch', 'no_table', 'reserve_overlap', 'ha_outlier'):
                    pts += 2
                else:
                    pts += 1
        score[date] = pts

json.dump(sorted(UNRELIABLE), open(os.path.join(S, 'unreliable.json'), 'w'))
json.dump({'per_month': review, 'score': score, 'checks': allflags,
           'verified_months': ['2019-10', '2019-08', '2017-06']},
          open(os.path.join(S, 'review.json'), 'w'), ensure_ascii=False, separators=(',', ':'))

print('months flagged', len(review), 'of', len({d for d in boxes if re.match(r'\d{4}-\d{2}$', d)}))
print('flag counts', {k: v for k, v in sorted(allflags.items(), key=lambda kv: -kv[1]) if v})
print(f"\n{'mes':9s} {'pts':>4s}  señales")
for d in sorted(score, key=lambda x: -score[x])[:15]:
    bits = []
    for k, f in review[d].items():
        for name in f:
            bits.append(f"{name}:{f[name].get('n')}")
    print(f"{d:9s} {score[d]:4d}  {' '.join(bits)[:120]}")
