#!/usr/bin/env python3
"""Parse the MICI / DNRM monthly licence listados into site_build/listados.json.

Input : site_build/listado_pdfs/<YYYY-MM>_<metal|nometal>_<contratos|solicitudes>.pdf
        (see get_listados.py) and site_build/listados_src.json for the source URL.
Output: site_build/listados.json
        {"YYYY-MM|kind": {"source": url, "rows": [
            {"code","type","company","has","zones","status","active"}, ...]}}

The PDFs are Excel exports: every table cell is its own text block, so the
layout is recovered from `pdftotext -bbox-layout` word coordinates instead of
the fixed-width text grid (which silently merges overflowing cells).
"""
import datetime
import json
import os
import re
import subprocess
import sys
import unicodedata
import xml.etree.ElementTree as ET
from bisect import bisect_right

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PDFDIR = os.path.join(ROOT, 'site_build', 'listado_pdfs')
SRC = os.path.join(ROOT, 'site_build', 'listados_src.json')
OUT = os.path.join(ROOT, 'site_build', 'listados.json')
NS = '{http://www.w3.org/1999/xhtml}'
TODAY = datetime.date(2026, 11, 17)

KINDS = ('metal/contratos', 'metal/solicitudes', 'nometal/contratos', 'nometal/solicitudes')

MESES = {'enero': 1, 'febrero': 2, 'marzo': 3, 'abril': 4, 'mayo': 5, 'junio': 6,
         'julio': 7, 'agosto': 8, 'septiembre': 9, 'setiembre': 9, 'octubre': 10,
         'noviembre': 11, 'diciembre': 12}

# header word (normalised) -> canonical column name
HKEYS = [
    (re.compile(r'^no?\.?$'), 'num'),
    (re.compile(r'^(exp\.?|expediente|n[°o]? ?expediente)$'), 'exp'),
    (re.compile(r'^simbolo'), 'symbol'),
    (re.compile(r'^tipo'), 'tipo'),
    (re.compile(r'^(fecha|entrada)'), 'fecha'),
    (re.compile(r'^empresa'), 'empresa'),
    (re.compile(r'^(material|mineral)'), 'mineral'),
    (re.compile(r'^localizaci'), 'loc'),
    (re.compile(r'^zonas?$'), 'zonas'),
    (re.compile(r'^has$'), 'has'),
    (re.compile(r'^(estatus|status)$'), 'status'),
    (re.compile(r'^resoluc'), 'resol'),
]


def norm(s):
    if s is None:
        return ''
    s = unicodedata.normalize('NFKD', s)
    s = ''.join(c for c in s if not unicodedata.combining(c))
    s = s.replace('º', 'o').replace('°', 'o')
    return s.lower()


def clean(s):
    return re.sub(r'\s+', ' ', (s or '')).strip()


# --------------------------------------------------------------------------- pdf
def pdf_blocks(path):
    """[[block, ...], ...] per page; block = dict(x0,y0,x1,y1,text,words)."""
    try:
        xml = subprocess.run(['pdftotext', '-bbox-layout', path, '-'],
                             capture_output=True, text=True, timeout=180).stdout
        root = ET.fromstring(xml)
    except Exception as e:
        print(f"  !! pdftotext failed on {path}: {e}", file=sys.stderr)
        return []
    pages = []
    for pg in root.iter(NS + 'page'):
        blocks = []
        for b in pg.iter(NS + 'block'):
            words = []
            for w in b.iter(NS + 'word'):
                t = (w.text or '').strip()
                if not t:
                    continue
                words.append((t, float(w.get('xMin')), float(w.get('yMin')),
                              float(w.get('xMax')), float(w.get('yMax'))))
            if not words:
                continue
            blocks.append({
                'x0': min(w[1] for w in words), 'y0': min(w[2] for w in words),
                'x1': max(w[3] for w in words), 'y1': max(w[4] for w in words),
                'words': words,
                'text': clean(' '.join(w[0] for w in words)),
            })
        pages.append(blocks)
    return pages


def word_lines(blocks):
    """Group words of a page into visual lines: [(y_center, [(text,x0,y0,x1,y1), ...]), ...]."""
    words = [w for b in blocks for w in b['words']]
    words.sort(key=lambda w: (w[2], w[1]))
    lines = []
    for w in words:
        cy = (w[2] + w[4]) / 2
        if lines and abs(lines[-1][0] - cy) <= 4.0:
            lines[-1][1].append(w)
            lines[-1][0] = (lines[-1][0] * (len(lines[-1][1]) - 1) + cy) / len(lines[-1][1])
        else:
            lines.append([cy, [w]])
    for ln in lines:
        ln[1].sort(key=lambda w: w[1])
    return [(y, ws) for y, ws in lines]


def line_semantics(words):
    out = {}
    for (t, x0, y0, x1, y1) in words:
        n = norm(t).strip('.').strip()
        for rx, name in HKEYS:
            if rx.match(n):
                out.setdefault(name, []).append(x0)
                break
    return out


STOPWORDS = {'de', 'del', 'la', 'el', 'n', 'solicitud', 'solicitudes', 'y'}


def header_info(blocks):
    """(semantic -> x of the header label, set(header block indices)).

    Each header label of these Excel exports is its own text block, so a block
    that is uppercase, digit-free and made only of column keywords (+stop
    words) is a header block.
    """
    cols, hdr = {}, set()
    for i, b in enumerate(blocks):
        txt = b['text']
        if not txt or re.search(r'\d', txt) or txt.upper() != txt:
            continue
        sem = line_semantics(b['words'])
        if not sem:
            continue
        stop = sum(1 for w in b['words'] if norm(w[0]).strip('.') in STOPWORDS)
        if sum(len(v) for v in sem.values()) + stop != len(b['words']):
            continue
        hdr.add(i)
        for name, xs in sem.items():
            cols[name] = min(cols.get(name, 1e9), min(xs))
    if len(cols) < 3:
        return None, set()
    return cols, hdr


def column_edges(data_blocks):
    """Cluster data-cell left edges; returns ascending list of cluster minima."""
    xs = sorted(b['x0'] for b in data_blocks)
    clusters = []
    for x in xs:
        if clusters and x - clusters[-1][-1] <= 6:
            clusters[-1].append(x)
        else:
            clusters.append([x])
    return [c[0] for c in clusters if len(c) >= 2]


def match_columns(hdr, edges):
    """semantic -> left edge.  Header words are centred, data cells are flush left."""
    sem = sorted(hdr.items(), key=lambda kv: kv[1])
    out, pi = {}, 0
    for i, (name, x) in enumerate(sem):
        last = i == len(sem) - 1
        cand = [(j, e) for j, e in enumerate(edges) if j >= pi]
        if not cand:
            break
        if last:
            j, e = cand[0]                      # status column: first edge right of the rest
        else:
            j, e = min(cand, key=lambda je: abs(je[1] - x))
        out[name] = e
        pi = j + 1
    return out


# ------------------------------------------------------------------------ values
NUMRE = re.compile(r'\d[\d.,]*')


def to_float(s):
    m = NUMRE.search(s or '')
    if not m:
        return None
    t = m.group(0).replace(',', '')
    if t.count('.') > 1:                       # 1.234.567 -> thousands dots
        t = t.replace('.', '')
    try:
        v = float(t)
    except ValueError:
        return None
    if v < 0 or v > 5_000_000:
        return None
    return v


def to_int(s):
    v = to_float(s)
    return int(v) if v is not None and v == int(v) else None


DATEMON = '|'.join(sorted(MESES, key=len, reverse=True))
RX_D1 = re.compile(r'(\d{1,2})\s*(?:de\s*)?(' + DATEMON + r')\.?\s*(?:de(?:l)?\s*)?(\d{4})')
RX_D2 = re.compile(r'\b(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})\b')


def dates_in(text):
    s = norm(text or '')
    out = []
    for d, mo, y in RX_D1.findall(s):
        try:
            out.append(datetime.date(int(y), MESES[mo], int(d)))
        except ValueError:
            pass
    for d, mo, y in RX_D2.findall(s):
        y = int(y)
        y = y + 2000 if y < 100 else y
        try:
            out.append(datetime.date(y, int(mo), int(d)))
        except ValueError:
            pass
    return out


RX_DEAD = re.compile(r'cancelad|caducad|renuncia|revocad|extinguid|clausurad|suspendid')
RX_EXPIRE = re.compile(r'vencid|vencimiento|vence|vencio')


def is_active(status):
    s = norm(status)
    ds = dates_in(status)
    past = [d for d in ds if d < TODAY]
    future = [d for d in ds if d >= TODAY]
    if RX_DEAD.search(s):
        return False if (past or not ds) else True
    if RX_EXPIRE.search(s):
        return bool(future)
    return True


# ------------------------------------------------------------------------- parse
def cell_text(words):
    """Join the words of one cell in reading order.

    The wide STATUS cell of the Excel export sometimes holds two text runs on
    the same baseline (Contrato/Gaceta/VENCE  |  Cancelado por Resolución ...).
    Clustering the *line* left edges recovers those sub-columns; each one is
    then read line by line.
    """
    if not words:
        return ''
    words = sorted(words, key=lambda w: ((w[2] + w[4]) / 2, w[1]))
    lines, cur = [], [words[0]]
    for w in words[1:]:
        cy = (w[2] + w[4]) / 2
        cy_cur = (cur[0][2] + cur[0][4]) / 2
        if abs(cy - cy_cur) <= 4.0:
            cur.append(w)
        else:
            lines.append(cur)
            cur = [w]
    lines.append(cur)
    for ln in lines:
        ln.sort(key=lambda w: w[1])
    # sub-columns: cluster lines by their left edge
    groups = []
    for ln in lines:
        x0 = ln[0][1]
        if groups and x0 - groups[-1][0] <= 30:
            groups[-1][1].append(ln)
        else:
            groups.append([x0, [ln]])
    return clean(' '.join(' '.join(w[0] for w in ln) for _, g in groups for ln in g))


def parse_pdf(path):
    pages = pdf_blocks(path)
    if not pages:
        return []
    rows = []
    prev_geom = None
    for pno, blocks in enumerate(pages, 1):
        hdr, hset = header_info(blocks)
        if hdr is None:
            if prev_geom is None:
                continue
            cols = prev_geom
            data = list(blocks)
        else:
            data = [b for i, b in enumerate(blocks) if i not in hset]
            edges = column_edges(data)
            if not edges:
                continue
            cols = match_columns(hdr, edges)
            prev_geom = cols
        if not data or 'num' not in cols:
            continue
        e = sorted(cols.values())
        names = [n for n, v in sorted(cols.items(), key=lambda kv: kv[1])]
        bounds = list(e) + [1e9]

        def col_of(b):
            best, bi = -1.0, 0
            for i in range(len(e)):
                ov = min(b['x1'], bounds[i + 1]) - max(b['x0'], bounds[i])
                if ov > best:
                    best, bi = ov, i
            return names[bi]

        bycol = {}
        for b in data:
            bycol.setdefault(col_of(b), []).append(b)

        # one row per company cell (some rows have no N° cell at all: merged
        # cells of the two "Contrato Ley" concessions are a known case)
        seeds = []
        for b in bycol.get('empresa', []):
            seeds.append(((b['y0'] + b['y1']) / 2, 1))
        for b in bycol.get('num', []):
            if re.fullmatch(r'\d{1,4}', b['text']):
                seeds.append(((b['y0'] + b['y1']) / 2, 0))
        if not seeds:
            continue
        seeds.sort()
        sy, cur = [], []
        for y, kind in seeds:
            if cur and y - cur[-1] <= 8:
                cur.append(y)
            else:
                if cur:
                    sy.append(sum(cur) / len(cur))
                cur = [y]
        if cur:
            sy.append(sum(cur) / len(cur))
        gaps = [b - a for a, b in zip(sy, sy[1:])]
        step = sorted(gaps)[len(gaps) // 2] if gaps else 60.0
        buckets = [dict() for _ in sy]

        def rng(name):
            i = names.index(name)
            return bounds[i], bounds[i + 1]

        for b in data:
            cy = (b['y0'] + b['y1']) / 2
            k = min(range(len(sy)), key=lambda i: abs(sy[i] - cy))
            if abs(sy[k] - cy) > max(0.75 * step, 25):
                continue
            c = col_of(b)
            ws = b['words']
            if c == 'empresa':
                lim = cols.get('mineral') or cols.get('loc') or 1e9
                ws = [w for w in ws if w[1] < lim]
            elif c not in ('status',):
                lo, hi = rng(c)
                keep = [w for w in ws if lo - 6 <= w[1] < hi]
                ws = keep or ws
            else:
                lo, _ = rng('status')
                ws = [w for w in ws if w[1] >= lo - 6]
            buckets[k].setdefault(c, []).extend(ws)
            buckets[k].setdefault('_all', []).extend(b['words'])

        for bk in buckets:
            cell = {n: cell_text(v) for n, v in bk.items()}
            code = clean(cell.get('exp') or cell.get('num') or '')
            m = re.search(r'\b(\d{2,4}-\d{1,4})\b', code)
            if not m:
                # the EXP cell of a merged row can be filed under another column
                for w in sorted(bk.get('_all', []), key=lambda w: w[1]):
                    m = re.search(r'\d{2,4}-\d{1,4}', w[0])
                    if m:
                        break
            if m:
                code = m.group(0)
            if not m:
                # a few rows (the two "Contrato Ley" concessions) carry no
                # expediente at all; their status cites the contract-law number
                m2 = re.search(r'contrato\s+ley\s*n[°ºo]?\.?\s*(\d+)', norm(cell.get('status', '')))
                if m2:
                    code = 'CL-' + m2.group(1)
            # numeric columns: scan the row band by x, some exports merge the
            # HAS value into the wide STATUS block
            allw = bk.get('_all', [])
            if 'zonas' in cols and 'has' in cols:
                zlo, zhi = cols['zonas'], cols['has']
                hlo, hhi = cols['has'], cols.get('status', 1e9)
                zt = [w[0] for w in sorted(allw, key=lambda w: w[1])
                      if zlo - 4 <= w[1] < zhi and re.fullmatch(r'\d{1,3}', w[0])]
                ht = [w[0] for w in sorted(allw, key=lambda w: w[1])
                      if hlo - 4 <= w[1] < hhi]
                zones = next((to_int(t) for t in zt if to_int(t) is not None),
                             to_int(cell.get('zonas', '')))
                has = next((to_float(t) for t in ht if to_float(t) is not None),
                           to_float(cell.get('has', '')))
            else:
                zones = to_int(cell.get('zonas', ''))
                has = to_float(cell.get('has', ''))
            status = clean(cell.get('status', ''))
            rows.append({
                'code': code,
                'page': pno,
                'type': clean(cell.get('tipo', '')) or None,
                'company': clean(cell.get('empresa', '')) or None,
                'has': has,
                'zones': zones,
                'status': status,
                'active': is_active(status),
            })
    return rows


def main():
    maps = json.load(open(os.path.join(ROOT, 'data_pdf.json')))
    months = {m['date'] for m in maps}
    for f in os.listdir(PDFDIR):
        m2 = re.match(r'(\d{4}-\d{2})_', f)
        if m2:
            months.add(m2.group(1))
    months = sorted(months)
    src = {}
    if os.path.exists(SRC):
        src = json.load(open(SRC))

    out = {}
    for mo in months:
        for kind in KINDS:
            key = f"{mo}|{kind}"
            p = os.path.join(PDFDIR, f"{mo}_{kind.replace('/', '_')}.pdf")
            if not os.path.exists(p):
                continue
            rows = parse_pdf(p)
            seen, keep = set(), []
            for r in rows:
                if not r['code'] or r['code'] in seen:
                    continue
                seen.add(r['code'])
                keep.append(r)
            if not keep:
                print(f"  (empty) {key}")
                continue
            out[key] = {'source': (src.get(key) or {}).get('url', ''), 'rows': keep}

    json.dump(out, open(OUT, 'w'), ensure_ascii=False, indent=1, sort_keys=True)
    print(f"wrote {OUT}: {len(out)} keys")

    # ---------------------------------------------------------------- report
    print(f"{'month':9s} {'kind':20s} {'rows':>5s} {'has':>5s} {'zon':>5s} {'active':>7s}")
    tot = 0
    goods = 0
    for key in sorted(out):
        rows = out[key]['rows']
        a = sum(1 for r in rows if r['active'])
        nh = sum(1 for r in rows if r['has'] is not None)
        nz = sum(1 for r in rows if r['zones'] is not None)
        mo, kind = key.split('|')
        print(f"{mo:9s} {kind:20s} {len(rows):5d} {nh:5d} {nz:5d} {a * 100 // len(rows):6d}%")
        tot += 1
        if len(rows) >= 20:
            goods += 1
    print(f"\nkeys: {tot}   keys with >=20 rows: {goods}")
    for key in ('2024-09|nometal/contratos', '2025-06|nometal/solicitudes', '2022-05|metal/contratos'):
        if key in out:
            rows = out[key]['rows']
            print(f"  sample {key}: {len(rows)} rows, active={sum(r['active'] for r in rows)}/{len(rows)}")


if __name__ == '__main__':
    main()
