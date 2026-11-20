"""Build site/licrows.json — where each licence code sits in its month's LISTADO.

{"YYYY-MM|kind": {"CODE": {"f": global ordinal, "p": page, "r": row on that page}}}

`r` is what a reader can locate: the ordinal restarts on every page, because the
PDFs print no row numbers. `p` feeds the #page= anchor of the evidence link.
"""
import json, os, re, sys

GLYPH = str.maketrans('OILSB', '01158')
CODE_RE = re.compile(r'([0-9OILSB]{2,4})[-\u2013\u2014_,.:]([0-9OILSB]{1,3})(?![0-9])')

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, 'site_build', 'listados.json')
OUT = os.path.join(ROOT, 'site', 'licrows.json')


def norm_code(raw):
    """Mirror of join_codes.norm_code ('83-6' -> ('83-06'))."""
    t = re.sub(r'\s+', '', (raw or '').upper())
    m = CODE_RE.search(t)
    if not m:
        return None
    pre, suf = m.group(1).translate(GLYPH), m.group(2).translate(GLYPH)
    if not pre.isdigit() or not suf.isdigit():
        return None
    return '%s-%s' % (pre, suf.zfill(2) if len(suf) == 1 else suf)


def build():
    out = {}
    for key, v in json.load(open(SRC)).items():
        m, per_page = {}, {}
        for i, r in enumerate(v.get('rows') or [], 1):
            c = r.get('code')
            if not c:
                continue
            p = r.get('page') or 1
            per_page[p] = per_page.get(p, 0) + 1
            if c not in m:
                m[c] = {'f': i, 'p': p, 'r': per_page[p]}
                n = norm_code(c)
                if n and n != c and n not in m:
                    m[n] = dict(m[c], _alias=True)
        if m:
            out[key] = m
    return out


def main():
    new = build()
    old = {}
    if os.path.exists(OUT):
        old = json.load(open(OUT))
    drift = 0
    for key, m in new.items():
        for code, v in m.items():
            o = (old.get(key) or {}).get(code)
            if o and o.get('f') != v['f']:
                drift += 1
    json.dump(new, open(OUT, 'w'), separators=(',', ':'))
    print('keys', len(new), 'codes', sum(len(v) for v in new.values()),
          'row drift vs previous', drift, flush=True)


if __name__ == '__main__':
    main()
