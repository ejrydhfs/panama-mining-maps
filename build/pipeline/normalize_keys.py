"""Add canonical (norm_code) aliases to license.json and licrows.json.

The map's codes come from join_codes.norm_code() ('83-6' -> '83-06', '2005.03' ->
'2005-03'), while the listado tables keep the cell text ('83-6'). A code that only
matches after normalisation lost both its ficha and its page citation, so the alias
is added rather than the raw key renamed (raw stays authoritative).
"""
import json, os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'site_build'))
from join_codes import norm_code

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
