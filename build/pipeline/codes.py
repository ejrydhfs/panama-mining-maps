"""Extrae los codigos de licencia impresos en cada hoja de mapa a
site_build/codes/<date>_<kind>.json = {"file","w","h","codes":[[code,cx,cy],...]}
en pixeles del render de 200 dpi.

Cada hoja es un unico raster (9600x7200 px a 200 dpi) con ~150-300 etiquetas
en dos estilos: texto blanco de 12-16 px de alto y, para los expedientes de
4 digitos (2000-xx), texto negro sobre una placa blanca redondeada.  Un barrido
de tesseract sobre la pagina completa no sirve: psm 11 devuelve ~100 tokens de
los que 1-2 son codigos (medido sobre 354_mapa-de-contratos-metalicos-enero-
2022.pdf), y psm 7 sobre un recorte devuelve "94591" donde dice "94-59 Z1".
El pipeline por tanto es:

  1. render de la pagina 1 a 200 dpi (pdftoppm, jpeg q90, nombre por PID).
  2. localizacion barata de los dos estilos de etiqueta (<2 s por hoja):
     - glifos blancos: mascara (s<85, v>168), componentes de 6-27 px de alto,
       dilatacion horizontal (13x3) para agrupar la palabra, filtro de caja;
     - placas blancas: componentes casi rellenos (v>195, s<55) de 40-420 px
       de ancho y 15-80 px de alto, aspecto >= 1.5.
  3. reconocimiento por lotes con el recognizer de RapidOCR sobre los recortes
     reescalados 3x (32 por llamada, ~10 s por hoja).  Se usa solo el CRNN, no
     el detector: a esta escala el detector de RapidOCR reescala la imagen y
     pierde los glifos, mientras que el recorte ampliado se lee con conf 0.8.
     Las etiquetas dudosas (expediente de un solo digito tras el guion) se
     releen sobre el recorte binarizado sin la sombra roja, que es la que
     hace perder un digito ('90-0 T1' -> '90-07Z1'), y toda etiqueta se
     contrasta con dos relecturas a escala 2x y 5x para corregir el sufijo.
     Tesseract (psm 11 whitelist + libre) queda como pasada sobre la pagina
     completa, pero solo se aprovecha el codigo que el listado confirma:
     suelto aporta una etiqueta por hoja y bastante ruido.
  4. normalizacion (el guion se imprime/lee como ':' '.' '_' '/' y la Z como
     2 o 7), regex de codigo (expediente de 2 o 4 digitos + zona Z1-Z9),
     reparacion contra el listado del mes cuando existe (sustitucion unica, o
     insercion para completar un expediente de 4 digitos leido con 3), dedupe
     por posicion (<18x10 px: la misma etiqueta suele detectarse dos veces,
     como glifo y como placa) y descarte del 3 % de margen exterior.
"""
import csv
import json
import os
import re
import subprocess
import sys
import time
from multiprocessing import Pool

import cv2
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUTDIR = os.path.join(HERE, 'codes')
TMP = os.environ.get('TMPDIR') or os.path.join(ROOT, '.work')

DPI = 200
MARGIN = 0.03
WL = '0123456789-ZT'
CONF = 0.40
CHUNK = 32       # recortes por llamada al recognizer
UP = 3           # reescalado del recorte antes del recognizer

# Codigo impreso: 2-4 digitos de ano/expediente, guion, 1-3 digitos y sufijo
# de zona opcional (Z1..Z9 / T1).  La barra de zona a veces se lee como 2 (Z)
# o 7 (T), por eso se admite en la reparacion.
CODE_Z = re.compile(r'^(\d{2,4})-(\d{1,3})([ZT])(\d)$')
CODE_P = re.compile(r'^(\d{2,4})-(\d{1,4})$')
CODE_M = re.compile(r'^(\d{2,4})-(\d{1,3})([27])(\d)$')
ANY = re.compile(r'\d{2,4}-\d{1,4}[A-Z]?\d?')

_ocr = None


def get_ocr():
    """RapidOCR con la detección desactivada a mano cuando solo se usa el
    recognizer (se abarata el arranque y no se cargan los modelos de det)."""
    global _ocr
    if _ocr is None:
        from rapidocr_onnxruntime import RapidOCR
        _ocr = RapidOCR(use_angle_cls=False)
    return _ocr


# ------------------------------------------------------------- normalizar
def norm(txt):
    t = txt.replace('\u2013', '-').replace('\u2014', '-').replace('\u2212', '-')
    # el guion se lee como ':' '.' '_' o '/' con frecuencia ('90.07z1')
    t = re.sub(r'[.:_/]', '-', t)
    return re.sub(r'\s+', '', t.upper())


def parse_code(raw):
    """'94-59z1' -> '94-59 Z1'; '4-07 z1' -> '04-07 Z1'; None si no es codigo.

    El expediente tiene 2 o 4 digitos (los 4 son los anos 1980-2026); 3 digitos
    es una lectura truncada y solo se acepta si repair() la completa contra el
    listado del mes."""
    t = norm(raw)
    if not t:
        return None
    for rx, zone in ((CODE_Z, True), (CODE_M, True), (CODE_P, False)):
        m = rx.match(t)
        if not m:
            continue
        pre, suf = m.group(1), m.group(2)
        if len(pre) == 1:
            pre = '0' + pre
        if zone:
            zd = m.group(4)
            # la letra de zona impresa es siempre Z: 13 etiquetas con "T"
            # muestreadas en 6 hojas distintas dicen Z1/Z2 (el recognizer
            # convierte la Z en T o en 2 cuando el glifo es rojo con borde
            # blanco), asi que T se normaliza a Z.
            return '%s-%s Z%s' % (pre, suf, zd)
        return '%s-%s' % (pre, suf)
    return None


def codes_in(text):
    """Codigos contenidos en una cadena OCR (puede traer basura alrededor)."""
    t = norm(text)
    one = parse_code(t)
    if one:
        return [one]
    out = []
    for m in ANY.finditer(t):
        c = parse_code(m.group(0))
        if c:
            out.append(c)
    return out


def first_code(text):
    """Primer codigo de una lectura OCR, o None."""
    got = codes_in(text) if text else []
    return got[0] if got else None


def edit1(a, b):
    """Distancia de edicion <= 1 (solo sustituciones de un caracter)."""
    if len(a) != len(b):
        return False
    return sum(x != y for x, y in zip(a, b)) == 1


def repair(code, lexicon):
    """Ajusta el codigo leido al listado del mes.

    - Si esta en el listado se deja tal cual.
    - Si el expediente tiene 3 digitos (lectura truncada de un ano de 4) se
      prueba a insertar un digito en cada posicion: solo se acepta cuando hay
      exactamente un codigo del listado que encaja.
    - Si no, un unico codigo del listado a una sustitucion de distancia
      (confusiones 2/Z, 7/T, 0/8, 1/7 de la tipografia).
    - Sin listado (hojas anteriores a 2022-06) se descartan los expedientes de
      3 digitos y el resto se deja como se leyo.
    """
    pre, _, suf = code.partition('-')
    if not lexicon:
        return None if len(pre) == 3 else code
    if code in lexicon:
        return code
    if len(pre) == 3:
        cand = []
        for i in range(4):
            for d in '0123456789':
                c = pre[:i] + d + pre[i:] + '-' + suf
                if c in lexicon:
                    cand.append(c)
        return cand[0] if len(cand) == 1 else None
    cand = [c for c in lexicon if edit1(c, code)]
    return cand[0] if len(cand) == 1 else code



# ------------------------------------------------------------------ render
def render(pdf, base):
    jpg = base + '-1.jpg'
    subprocess.run(['pdftoppm', '-f', '1', '-l', '1', '-r', str(DPI),
                    '-jpeg', '-jpegopt', 'quality=90', pdf, base],
                   check=True, stdout=subprocess.DEVNULL,
                   stderr=subprocess.DEVNULL)
    return jpg


def parts(code):
    """'90-07 Z1' -> ('90-07', 'Z1')."""
    base, _, zone = code.partition(' ')
    return base, zone


def doubtful(code):
    """Lectura que merece releerse: expediente de 1 digito tras el guion
    (falta un digito) o zona leida como T (en las hojas la letra es Z)."""
    base, zone = parts(code)
    return len(base.split('-')[1]) == 1 or zone.startswith('T')


def better(new, old):
    """La relectura solo se acepta si aporta digitos o arregla Z/T."""
    nb, nz = parts(new)
    ob, oz = parts(old)
    if len(nb.split('-')[1]) > len(ob.split('-')[1]):
        return True
    return nb == ob and nz.startswith('Z') and oz.startswith('T')


def clean_glyphs(crop):
    """Binariza los glifos blancos de un recorte (quita la sombra roja y el
    fondo, que es lo que hace que el recognizer pierda un digito)."""
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    m = (((hsv[:, :, 1] < 85) & (hsv[:, :, 2] > 168)).astype(np.uint8) * 255)
    ys, xs = np.where(m > 0)
    if len(ys) < 10:
        return None
    m = m[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    return cv2.cvtColor(m, cv2.COLOR_GRAY2BGR)


# ------------------------------------------------------------- localizacion
def find_boxes(bgr):
    """Cajas de palabras de texto blanco (glifos de 6-27 px de alto)."""
    H, W = bgr.shape[:2]
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    s = hsv[:, :, 1]
    v = hsv[:, :, 2]
    m = ((s < 85) & (v > 168)).astype(np.uint8)
    del hsv, s, v
    n, lab, stats, _ = cv2.connectedComponentsWithStats(m, 8)
    h = stats[:, cv2.CC_STAT_HEIGHT]
    w = stats[:, cv2.CC_STAT_WIDTH]
    a = stats[:, cv2.CC_STAT_AREA]
    ok = ((h >= 6) & (h <= 27) & (w >= 1) & (w <= 130) & (a >= 5) &
          (a <= 1600))
    ok[0] = False
    glyph = np.zeros(n, np.uint8)
    glyph[ok] = 255
    m = glyph[lab]
    del lab, glyph
    words = cv2.dilate(m, cv2.getStructuringElement(cv2.MORPH_RECT, (13, 3)))
    n2, lab2, st2, _ = cv2.connectedComponentsWithStats(words, 8)
    del words, lab2
    boxes = []
    for i in range(1, n2):
        x, y, bw, bh = st2[i, 0], st2[i, 1], st2[i, 2], st2[i, 3]
        if not (7 <= bh <= 34 and 12 <= bw <= 200):
            continue
        sub = m[y:y + bh, x:x + bw]
        if (sub.sum(0) > 0).sum() < 12 or sub.sum() / 255.0 < 25:
            continue
        boxes.append((int(x), int(y), int(bw), int(bh)))
    del m
    return boxes


def find_plates(bgr):
    """Etiquetas de codigo grande: texto negro sobre placa blanca redondeada
    (p.ej. '2004-20').  La mascara de glifos blancos no las ve, asi que se
    localiza la placa y se reconoce el recorte entero."""
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    s = hsv[:, :, 1]
    v = hsv[:, :, 2]
    m = ((v > 195) & (s < 55)).astype(np.uint8)
    del hsv, s, v
    n, lab, stats, _ = cv2.connectedComponentsWithStats(m, 8)
    del lab
    w = stats[:, cv2.CC_STAT_WIDTH]
    h = stats[:, cv2.CC_STAT_HEIGHT]
    a = stats[:, cv2.CC_STAT_AREA]
    ok = ((w >= 40) & (w <= 420) & (h >= 15) & (h <= 80) &
          (a >= 0.35 * w * h) & (a <= 0.98 * w * h) & (w >= 1.5 * h))
    ok[0] = False
    idx = np.where(ok)[0]
    return [(int(stats[i, 0]) - 2, int(stats[i, 1]) - 2,
             int(stats[i, 2]) + 4, int(stats[i, 3]) + 4) for i in idx]


# ---------------------------------------------------------------------- OCR
def rec_crops(ocr, crops):
    """Reconoce una lista de recortes; devuelve [(texto, conf)] en orden."""
    rec = ocr.text_recognizer
    out = []
    for i in range(0, len(crops), CHUNK):
        part = crops[i:i + CHUNK]
        got, _ = rec(part)
        if len(got) != len(part):
            got = (got + [('', 0.0)] * len(part))[:len(part)]
        out.extend(got)
    return out


def fullpage(jpg, base):
    """tesseract psm 11 (whitelist + libre) sobre la pagina completa."""
    out = []
    for name, extra in (('w', ['-c', 'tessedit_char_whitelist=' + WL]),
                        ('u', [])):
        stem = '%s_%s' % (base, name)
        subprocess.run(['tesseract', jpg, stem, '-l', 'spa', '--psm', '11',
                        '-c', 'tessedit_create_tsv=1'] + extra,
                       check=True, stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL)
        path = stem + '.tsv'
        with open(path, newline='', encoding='utf-8', errors='replace') as f:
            for r in csv.DictReader(f, delimiter='\t', quoting=csv.QUOTE_NONE):
                txt = (r.get('text') or '').strip()
                if not txt:
                    continue
                for code in codes_in(txt):
                    try:
                        cx = int(r['left']) + int(r['width']) / 2.0
                        cy = int(r['top']) + int(r['height']) / 2.0
                        cf = float(r['conf']) / 100.0
                    except (TypeError, ValueError):
                        continue
                    out.append((code, cx, cy, cf))
        os.unlink(path)
    return out


# ------------------------------------------------------------------ proceso
def load_lexicon():
    path = os.path.join(HERE, 'listados.json')
    try:
        with open(path) as f:
            return json.load(f)
    except OSError:
        return {}


def process(job):
    name, sid, pdf, fname, key = job
    t0 = time.time()
    base = None
    try:
        base = os.path.join(TMP, 'codes_%d_%s' % (
            os.getpid(), re.sub(r'[^a-z0-9]+', '', sid.lower())[:20]))
        jpg = render(pdf, base)
        bgr = cv2.imread(jpg)
        if bgr is None:
            raise RuntimeError('jpeg ilegible')
        H, W = bgr.shape[:2]

        boxes = find_boxes(bgr) + find_plates(bgr)
        mx, my = W * MARGIN, H * MARGIN
        keep = []
        for (x, y, w, h) in boxes:
            cx, cy = x + w / 2.0, y + h / 2.0
            if mx <= cx <= W - mx and my <= cy <= H - my:
                keep.append((x, y, w, h))
        crops, centres, raw = [], [], []
        for (x, y, w, h) in keep:
            p = 4
            crop = bgr[max(0, y - p):y + h + p, max(0, x - p):x + w + p]
            if crop.size == 0:
                continue
            raw.append(crop)
            crops.append(cv2.resize(crop, None, fx=UP, fy=UP,
                                    interpolation=cv2.INTER_CUBIC))
            centres.append((x + w / 2.0, y + h / 2.0))
        del bgr

        ocr = get_ocr()
        lex = get_lexicon(key)
        got = []
        for i, ((cx, cy), (txt, cf)) in enumerate(zip(centres,
                                                     rec_crops(ocr, crops))):
            if float(cf) < CONF:
                continue
            for code in codes_in(txt):
                got.append((code, cx, cy, float(cf), i))
        del crops
        # tesseract sobre la pagina completa devuelve todo el texto del mapa;
        # sin listado no hay forma de distinguir un codigo real de una lectura
        # suelta, asi que solo se aprovecha cuando el listado lo confirma.
        if lex:
            got += [r + (-1,) for r in fullpage(jpg, base) if r[0] in lex]

        mx, my = W * MARGIN, H * MARGIN
        codes, seen = [], []
        for code, cx, cy, cf, idx in sorted(got, key=lambda r: -r[3]):
            code = repair(code, lex)
            if not code:
                continue
            if not (mx <= cx <= W - mx and my <= cy <= H - my):
                continue
            # una etiqueta se detecta dos veces (glifo suelto y placa/bloque)
            # y las dos lecturas pueden diferir en un caracter; manda la de
            # mayor confianza, que es la que llega primero
            if any(abs(ox - cx) < 18 and abs(oy - cy) < 10
                   for _, ox, oy in seen):
                continue
            seen.append((code, cx, cy))
            codes.append([code, round(cx, 1), round(cy, 1), idx])

        # Relectura de las etiquetas dudosas sobre el recorte binarizado
        # (glifos blancos, sin sombra): recupera el digito que se pierde por
        # la sombra roja ('90-0 T1' -> '90-07 Z1').
        doubt = [c for c in codes if c[3] >= 0 and doubtful(c[0])]
        if doubt:
            imgs, keep_d = [], []
            for c in doubt:
                g = clean_glyphs(raw[c[3]])
                if g is None:
                    continue
                imgs.append(cv2.resize(g, None, fx=4, fy=4,
                                       interpolation=cv2.INTER_CUBIC))
                keep_d.append(c)
            for c, (txt, cf) in zip(keep_d, rec_crops(ocr, imgs)):
                code2 = first_code(txt) if float(cf) >= CONF else None
                code2 = repair(code2, lex) if code2 else None
                if code2 and better(code2, c[0]):
                    c[0] = code2

        # segunda lectura del mismo recorte a otras dos escalas.  Solo se
        # corrige el sufijo de zona cuando las dos lecturas extra coinciden
        # entre si y con el expediente leido en la primera (el fallo tipico es
        # Z->T o Z->2, no el expediente entero).
        again = [c for c in codes if c[3] >= 0]
        votes = {}
        for up in (2, 5):
            part = [cv2.resize(raw[c[3]], None, fx=up, fy=up,
                               interpolation=cv2.INTER_CUBIC) for c in again]
            for c, (txt, cf) in zip(again, rec_crops(ocr, part)):
                code2 = first_code(txt) if float(cf) >= CONF else None
                code2 = repair(code2, lex) if code2 else None
                if code2:
                    votes.setdefault(tuple(c[:3]), []).append(code2)
        for c in again:
            v = votes.get(tuple(c[:3])) or []
            if (len(v) == 2 and v[0] == v[1] and v[0] != c[0] and
                    v[0].split(' ')[0] == c[0].split(' ')[0]):
                c[0] = v[0]
        codes = [c[:3] for c in codes]

        rec = {'file': fname, 'w': int(W), 'h': int(H), 'codes': codes}
        os.makedirs(OUTDIR, exist_ok=True)
        with open(os.path.join(OUTDIR, name + '.json'), 'w') as f:
            json.dump(rec, f, separators=(',', ':'))
        lexn = len(lex)
        hit = sum(1 for c in codes if not lexn or c[0] in lex)
        return (name, len(codes), len(boxes), hit, lexn,
                round(time.time() - t0, 1), None)
    except Exception as e:  # noqa: BLE001
        return (sid, 0, 0, 0, 0, round(time.time() - t0, 1),
                '%s: %s' % (type(e).__name__, e))
    finally:
        if base:
            for f in os.listdir(TMP):
                if f.startswith('codes_%d_' % os.getpid()):
                    try:
                        os.unlink(os.path.join(TMP, f))
                    except OSError:
                        pass


_LEX = None
_CACHE = {}


def get_lexicon(key):
    """Codigos esperados del listado del mes (cache por proceso)."""
    global _LEX
    if key not in _CACHE:
        if _LEX is None:
            _LEX = load_lexicon()
        codes = set()
        ent = _LEX.get(key)
        if ent:
            for r in ent['rows']:
                c = (r.get('code') or '').strip().upper()
                if re.match(r'^\d{2,4}-\d{1,3}$', c):
                    codes.add(c)
        _CACHE[key] = codes
    return _CACHE[key]


def resolve_jobs():
    sheets = json.load(open(os.path.join(ROOT, 'data_pdf.json')))
    man = json.load(open(os.path.join(ROOT, 'manifest_files.json')))
    byname = {}
    for r in man:
        loc = r.get('local')
        if loc and r.get('filename'):
            byname.setdefault(r['filename'], loc)
    jobs, missing, seen = [], 0, {}
    for s in sheets:
        loc = byname.get(s['file'])
        if not loc or not os.path.exists(os.path.join(ROOT, loc)):
            missing += 1
            print('FALTA', s['id'], s['file'], file=sys.stderr)
            continue
        # varias subidas distintas pueden compartir date|kind (duplicados del
        # sitio); la primera se queda con el nombre canonico y las demas con
        # sufijo _2, _3...
        seen[s['id']] = seen.get(s['id'], 0) + 1
        name = s['id'] if seen[s['id']] == 1 else '%s_%d' % (s['id'],
                                                            seen[s['id']])
        jobs.append((name, s['id'], os.path.join(ROOT, loc), s['file'],
                     '%s|%s' % (s['date'], s['kind'])))
    if missing:
        print('%d hojas sin PDF local' % missing, file=sys.stderr)
    return jobs


def main():
    os.makedirs(OUTDIR, exist_ok=True)
    os.makedirs(TMP, exist_ok=True)
    jobs = resolve_jobs()
    if '--resume' in sys.argv:
        done = {f.rsplit('.', 1)[0] for f in os.listdir(OUTDIR)
                if f.endswith('.json')}
        jobs = [j for j in jobs if j[0] not in done]
    only = [a for a in sys.argv[1:] if not a.startswith('-')]
    if only:
        jobs = [j for j in jobs if j[0] in only or j[1] in only]
    print('%d hojas a procesar' % len(jobs), flush=True)
    rows = []
    with Pool(4) as pool:
        for r in pool.imap_unordered(process, jobs, chunksize=1):
            rows.append(r)
            print('%s %d codigos (%d/%d en listado) %d cajas %.1fs%s' % (
                r[0], r[1], r[3], r[4], r[2], r[5],
                '' if r[6] is None else ' FALLO ' + r[6]), flush=True)
    ok = [r for r in rows if r[6] is None]
    cnt = sorted(r[1] for r in ok)
    med = cnt[len(cnt) // 2] if cnt else 0
    print('\nOK %d/%d  total %d  mediana %d  min %d  max %d' % (
        len(ok), len(rows), sum(cnt), med, cnt[0] if cnt else 0,
        cnt[-1] if cnt else 0))
    worst = sorted(ok, key=lambda r: r[1])[:3]
    for r in worst:
        print('peor: %s %d codigos' % (r[0], r[1]))


if __name__ == '__main__':
    main()
