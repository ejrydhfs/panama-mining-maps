"""Independent second read of every printed code, by re-running the label OCR at a
different scale (4x instead of 3x) and a lower confidence floor.

Both reads must agree on the same label position; a code that changes under the new
scale is not published with a company. Output: site/codecheck.json {"date|kind": [codes]}.
"""
import json, os, re, sys
from multiprocessing import Pool

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import codes as C

C.UP = 4
C.CONF = 0.30
C.OUTDIR = os.path.join(ROOT, '.work', 'codes4')


def base(code):
    m = re.match(r'(\d{2,4})-(\d{1,3})', str(code))
    return f'{int(m.group(1))}-{int(m.group(2)):02d}' if m else str(code)


def main():
    os.makedirs(C.OUTDIR, exist_ok=True)
    jobs = C.resolve_jobs()
    todo = [j for j in jobs if not os.path.exists(os.path.join(C.OUTDIR, j[0] + '.json'))]
    print('sheets', len(todo), 'of', len(jobs), flush=True)
    with Pool(6) as pool:
        for i, r in enumerate(pool.imap_unordered(C.process, todo, chunksize=1), 1):
            if i % 20 == 0:
                print('done', i, '/', len(todo), flush=True)
    out = {}
    old_dir = os.path.join(HERE, 'codes')
    for fn in sorted(os.listdir(C.OUTDIR)):
        if not fn.endswith('.json'):
            continue
        m = re.match(r'(\d{4}-\d{2})_(\w+)_(\w+)\.json', fn)
        if not m:
            continue
        key = f'{m.group(1)}|{m.group(2)}/{m.group(3)}'
        oldp = os.path.join(old_dir, fn)
        if not os.path.exists(oldp):
            continue
        old = json.load(open(oldp))['codes']
        new = json.load(open(os.path.join(C.OUTDIR, fn)))['codes']
        ok = set()
        for code, cx, cy, *_ in old:
            for code2, cx2, cy2, *_ in new:
                if abs(cx - cx2) < 18 and abs(cy - cy2) < 12 and base(code) == base(code2):
                    ok.add(base(code))
                    break
        if ok:
            out[key] = sorted(ok)
    json.dump(out, open(os.path.join(ROOT, 'site', 'codecheck.json'), 'w'), separators=(',', ':'))
    tot = sum(len(json.load(open(os.path.join(old_dir, f)))['codes'])
              for f in os.listdir(old_dir) if f.endswith('.json'))
    conf = sum(len(v) for v in out.values())
    print('confirmed', conf, 'of', tot, round(100 * conf / max(tot, 1)), '%', flush=True)


if __name__ == '__main__':
    main()
