"""Add canonical (norm_code) aliases to license.json.

The map's codes come from join_codes.norm_code() ('83-6' -> '83-06'), while the
listado tables keep the cell text ('83-6'). A code that only matches after
normalisation lost both its ficha and its page citation, so an alias key is added
next to the raw one (raw stays authoritative) and marked `_alias: True` so that no
count scores it twice. licrows.json carries the same aliases, emitted by
rows_index.py.
"""
import json, os, re

ROOT = os.environ.get('PANAMA_ROOT') or os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
GLYPH = str.maketrans('OILSB', '01158')
CODE_RE = re.compile(r'([0-9OILSB]{2,4})[-\u2013\u2014_,.:]([0-9OILSB]{1,3})(?![0-9])')
ZONE_RE = re.compile(r'Z\s*-?\s*(\d{1,2})')


def norm_code(raw):
    """Mirror of join_codes.norm_code: '90-07 Z1' -> ('90-07','Z1')."""
    t = re.sub(r'\s+', '', (raw or '').upper())
    if not t:
        return None, ''
    m = CODE_RE.search(t)
    if not m:
        return None, ''
    pre, suf = m.group(1).translate(GLYPH), m.group(2).translate(GLYPH)
    if not pre.isdigit() or not suf.isdigit():
        return None, ''
    z = ZONE_RE.search(t[m.end():])
    return '%s-%s' % (pre, suf.zfill(2) if len(suf) == 1 else suf), ('Z' + z.group(1)) if z else ''

S = os.path.join(ROOT, 'site')


def alias(path):
    data = json.load(open(path))
    added = 0
    for key, m in data.items():
        if not isinstance(m, dict):
            continue
        for code in list(m):
            n, _ = norm_code(code)
            if n and n != code and n not in m and not m[code].get('_alias'):
                alias_entry = dict(m[code])
                alias_entry['_alias'] = True
                m[n] = alias_entry
                added += 1
    json.dump(data, open(path, 'w'), separators=(',', ':'))
    return added


if __name__ == '__main__':
    for name in ('license.json',):
        n = alias(os.path.join(S, name))
        print(name, 'aliases added', n, flush=True)
