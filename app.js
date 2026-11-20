const MONTHS = ['ene','feb','mar','abr','may','jun','jul','ago','sep','oct','nov','dic'];
const CATS = [
  ['metal/contratos', 'metálicos · contratos', '#ff5c5c'],
  ['metal/solicitudes', 'metálicos · solicitudes', '#ffab40'],
  ['metal/ambos', 'metálicos · ambos', '#ffe082'],
  ['nometal/contratos', 'no metálicos · contratos', '#4da3ff'],
  ['nometal/solicitudes', 'no metálicos · solicitudes', '#2dd4bf'],
  ['nometal/ambos', 'no metálicos · ambos', '#8bd450'],
];
const COLOR = Object.fromEntries(CATS.map(([k, , c]) => [k, c]));

const state = {
  boxes: {}, sheets: {}, dates: [], i: 0, playing: null,
  active: new Set(CATS.map(c => c[0])), layer: null,
  codes: {}, lic: {}, licOk: false, onlyActive: false, onlyCoded: false, evidence: {}, kindFlags: {}, unreliable: new Set(), rowIdx: {}, renderMode: 'points', codeCheck: {}
};

const esc = s => String(s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

function canonCode(c) {
  const m = String(c).trim().match(/^(\d+)\s*-\s*(\d+)/);
  return m ? parseInt(m[1], 10) + '-' + parseInt(m[2], 10) : String(c).trim();
}
const trunc = (s, n) => { s = String(s); return s.length > n ? s.slice(0, n - 1) + '…' : s; };
const fmtHa = v => {
  if (v == null || v === '') return null;
  if (typeof v === 'number') return v.toLocaleString('es', { maximumFractionDigits: 2 }) + ' ha';
  const s = String(v).trim();
  return /ha\b/i.test(s) ? s : s + ' ha';
};

const map = L.map('map', { zoomControl: true, renderer: L.canvas({ padding: 0.5 }) }).setView([8.5, -80.1], 7);
map.attributionControl.setPrefix('');
map.attributionControl.addAttribution('Datos: MICI/DNRM · vía <a href="https://web.archive.org/web/*/mici.gob.pa/*">Wayback Machine</a>');

const mapLayer = L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png',
  { maxZoom: 19, opacity: 0.6, attribution: '&copy; OpenStreetMap' }).addTo(map);
const satLayer = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
  { maxZoom: 19, attribution: 'Imagery &copy; Esri, Maxar, Earthstar' });
let baseIsSat = false;

map.createPane('boxes').style.zIndex = 450;
const boxRenderer = L.canvas({ pane: 'boxes', padding: 0.5 });
boxRenderer.options.pane = 'boxes';

const label = d => { const [y, m] = d.split('-'); return `${MONTHS[+m - 1]} ${y}`; };

async function boot() {
  const [boxes, sheets, zones, evidence, kindFlags, unreliable, rowIdx, codeCheck, codes, lic] = await Promise.all([
    fetch('boxes.json?t=' + Date.now()).then(r => r.json()).catch(() => ({})),
    fetch('sheets.json?t=' + Date.now()).then(r => r.json()).catch(() => ({})),
    fetch('zones.json?t=' + Date.now()).then(r => r.json()).catch(() => []),
    fetch('evidence.json?t=' + Date.now()).then(r => r.json()).catch(() => ({})),
    fetch('kindflags.json?t=' + Date.now()).then(r => r.json()).catch(() => ({})),
    fetch('unreliable.json?t=' + Date.now()).then(r => r.json()).catch(() => []),
    fetch('licrows.json?t=' + Date.now()).then(r => r.json()).catch(() => ({})),
    fetch('codecheck.json?t=' + Date.now()).then(r => r.json()).catch(() => ({})),
    fetch('boxcodes.json?t=' + Date.now()).then(r => r.json()).catch(() => ({})),
    fetch('license.json?t=' + Date.now()).then(r => r.json()).catch(() => ({})),
  ]);
  state.zones = zones;
  state.evidence = evidence || {};
  state.kindFlags = kindFlags || {};
  state.unreliable = new Set(unreliable || []);
  state.rowIdx = rowIdx || {};
  state.codeCheck = codeCheck || {};
  state.codeSets = {};
  for (const [k, list] of Object.entries(state.codeCheck)) state.codeSets[k] = new Set(list.map(canonCode));
  state.gateOn = Object.keys(state.codeCheck).length > 0;
  state.boxes = boxes; state.sheets = sheets;
  state.codes = (codes && typeof codes === 'object') ? codes : {};
  state.lic = (lic && typeof lic === 'object') ? lic : {};
  state.licOk = Object.keys(state.lic).length > 0;
  state.dates = Object.keys(boxes).sort();
  buildChips(); buildYears(); bind(); drawZones(); bindModals();
  const only = document.getElementById('onlyActive');
  if (!state.licOk) {
    only.disabled = true;
    only.title = 'Sin datos de licencias';
    const sw = only.closest('.sw');
    if (sw) { sw.title = 'Sin datos de licencias vigentes'; sw.style.opacity = '.5'; sw.style.cursor = 'default'; }
  } else {
    only.disabled = false;
  }
  const sl = document.getElementById('slider');
  sl.max = Math.max(0, state.dates.length - 1);
  const want = new URLSearchParams(location.search).get('m');
  const startIdx = (want && state.dates.includes(want)) ? state.dates.indexOf(want) : state.dates.length - 1;
  render(startIdx);
  map.invalidateSize();
  map.fitBounds([[7.05, -83.4], [9.85, -77.0]], { padding: [12, 12] });
  window.addEventListener('resize', () => map.invalidateSize());
}

function drawZones() {
  if (!state.zoneLayer) state.zoneLayer = L.layerGroup();
  state.zoneLayer.clearLayers();
  for (const ring of (state.zones || [])) {
    L.polygon(ring.map(([x, y]) => [y, x]), {
      color: '#7ee787', weight: 1.2, opacity: .8, dashArray: '5 4',
      fillColor: '#7ee787', fillOpacity: .05, interactive: false
    }).addTo(state.zoneLayer);
  }
  if (state.zonesOn !== false) state.zoneLayer.addTo(map);
}

function buildChips() {
  const host = document.getElementById('cats');
  host.innerHTML = '';
  for (const [k, name, col] of CATS) {
    const el = document.createElement('div');
    el.className = 'chip on'; el.dataset.k = k;
    el.innerHTML = `<i style="background:${col}"></i>${name}`;
    el.onclick = () => {
      state.active.has(k) ? (state.active.delete(k), el.classList.remove('on'))
                          : (state.active.add(k), el.classList.add('on'));
      render(state.i);
    };
    host.appendChild(el);
  }
}

function buildYears() {
  const host = document.getElementById('years'); host.innerHTML = '';
  if (!state.dates.length) return;
  const a = +state.dates[0].slice(0, 4), b = +state.dates.at(-1).slice(0, 4);
  const n = state.dates.length - 1;
  const step = (b - a) > 12 ? 2 : 1;
  let last = -99;
  for (let y = a; y <= b; y += step) {
    const idx = state.dates.findIndex(d => d.startsWith(String(y)));
    if (idx < 0) continue;
    const pct = idx / (n || 1) * 100;
    if (pct - last < 5.5) continue;
    last = pct;
    const s = document.createElement('span');
    s.textContent = y; s.style.left = pct + '%';
    host.appendChild(s);
  }
}

function render(i) {
  state.i = i;
  const date = state.dates[i] || '';
  document.getElementById('date').textContent = label(date);
  document.getElementById('slider').value = i;

  if (state.layer) map.removeLayer(state.layer);
  const g = L.layerGroup();
  let n = 0, nAct = 0, nNoLic = 0, nCode = 0;
  const filter = state.onlyActive && state.licOk;
  const codedOnly = state.onlyCoded;
  const by = state.boxes[date] || {};
  for (const [kind, arr] of Object.entries(by)) {
    if (!state.active.has(kind)) continue;
    const col = COLOR[kind] || '#fff';
    const name = (CATS.find(c => c[0] === kind) || [0, kind])[1];
    const codes = state.codes[date + '|' + kind] || {};
    const licences = state.lic[date + '|' + kind] || {};
    const hasLic = Object.keys(licences).length > 0;
    for (let k = 0; k < arr.length; k++) {
      const [w, s, e, t] = arr[k];
      const code = codes[k];
      const hasCode = code != null && code !== '';
      const rec = hasCode ? licences[code] : undefined;
      const isAct = !!rec && rec.active === true;
      n++;
      if (isAct) nAct++;
      if (hasCode) nCode++;
      if (filter && !hasLic) nNoLic++;
      if (codedOnly && !hasCode) continue;
      if (filter && hasLic && !isAct) continue;
      let popup;
      if (hasCode) {
        const unreliableKey = state.unreliable.has(date + '|' + kind);
        const pdfEra = date >= '2021-12';
        const confirmed = !pdfEra || !state.gateOn ||
          (state.codeSets[date + '|' + kind] || new Set()).has(canonCode(code));
        const trusted = rec && !unreliableKey && confirmed;
        const bits = [`<b>${esc(code)}</b>` + (trusted ? ' <span style="color:#7ee787">✓ tabla</span>' : ' <span style="color:#ffc266">?</span>')];
        const who = [];
        let ficha = '';
        if (trusted && rec.company) {
          const bitsF = [esc(rec.company)];
          const haF = fmtHa(rec.has);
          if (haF) bitsF.push(esc(haF));
          ficha = `<details><summary style="cursor:pointer;color:#7cc4ff">ver ficha de la empresa</summary>` +
                  `<span style="color:#d7e0ec">${bitsF.join(' · ')}</span></details>`;
        }

        if (ficha) bits.push(ficha);
        let st = rec ? rec.status : 'sin ficha · atribución no verificada';
        if (unreliableKey) st = 'ficha no publicada: la tabla del mes y la hoja cubren códigos distintos';
        else if (rec && !confirmed) st = 'lectura no confirmada: la relectura a otra escala no coincide · ficha no publicada';
        const rc = (state.rowIdx[date + '|' + kind] || {})[code];
        const row = rc && rc.f, page = (rc && rc.p) || 1;
        const ev = (state.evidence[date + '|' + kind] || {}).table || {};
        let src = '';
        if (trusted) {
          src = `<span style="color:#8b96a5;font-size:11px">a fecha de: tabla LISTADO de ${label(date)}` +
                (row ? ` (pág. ${page}, fila ${row})` : '') + `</span> `;
          if (ev.url) src += `<a href="${ev.url}#page=${page}" target="_blank" rel="noopener" style="font-size:11px">ver tabla</a>`;
        }
        const kf = (state.kindFlags[date + '|' + kind] || {})[k];
        if (kf) st = `⚠ la tabla del mes lo lista como ${kf} — categoría dudosa · ` + st;
        if (st) bits.push(`<span style="color:#8b96a5">${esc(trunc(st, 160))}</span>`);
        if (src) bits.push(src);
        const rep = `https://github.com/ejrydhfs/panama-mining-maps/issues/new?title=` +
          encodeURIComponent(`Error ${date} ${kind} ${code}`) +
          `&body=` + encodeURIComponent(`Mes: ${date}\nCategoría: ${kind}\nCódigo: ${code}\nPolígono (W,S,E,N): ${w},${s},${e},${t}\n\nQué está mal y por qué:`);
        bits.push(`<span style="color:#8b96a5;font-size:10.5px">no prueba ilegalidad · no es un lindero · ` +
          `<a href="${rep}" target="_blank" rel="noopener">reportar error</a> · ` +
          `<a href="legal.html" target="_blank" rel="noopener">aviso legal</a></span>`);
        popup = `<div class="tt">${bits.join('<br>')}</div>`;
      } else {
        popup = `<div class="tt"><b>${name}</b><br>${((e - w) * 104).toFixed(1)} × ${((t - s) * 110).toFixed(1)} km` +
          `<br><span style="color:#8b96a5">${s.toFixed(3)}, ${w.toFixed(3)}</span></div>`;
      }
      const shape = state.renderMode === 'areas'
        ? L.rectangle([[s, w], [t, e]], { renderer: boxRenderer, color: col, weight: 1, opacity: .9,
                                           fillColor: col, fillOpacity: .16 })
        : L.circleMarker([(s + t) / 2, (w + e) / 2], { renderer: boxRenderer, radius: 3.2,
                                                       color: col, weight: 1, opacity: .95,
                                                       fillColor: col, fillOpacity: .85 });
      shape.bindPopup(popup, { closeButton: false }).addTo(g);
    }
  }
  state.layer = g.addTo(map);

  const sh = state.sheets[date] && Object.values(state.sheets[date])[0];
  const statEl = document.getElementById('stat');
  statEl.innerHTML = codedOnly
    ? `· ${nCode.toLocaleString('es')} con código / ${n.toLocaleString('es')} total`
    : filter
    ? `· ${nAct.toLocaleString('es')} vigentes / ${(n - nNoLic).toLocaleString('es')} con ficha` +
      (nNoLic ? ` <span title="mes sin tabla LISTADO: se muestran todos">· ${nNoLic.toLocaleString('es')} sin ficha</span>` : '')
    : n ? `· ${n.toLocaleString('es')} recintos` : '· sin datos';
  const srcEl = document.getElementById('src');
  if (srcEl) {
    if (sh && sh.url) { srcEl.href = sh.url; srcEl.textContent = sh.src === 'live' ? 'fuente' : 'wayback'; }
    else { srcEl.removeAttribute('href'); srcEl.textContent = ''; }
  }
}

function bind() {
  document.getElementById('slider').oninput = e => render(+e.target.value);
  const play = document.getElementById('play');
  play.onclick = () => {
    if (state.playing) { clearInterval(state.playing); state.playing = null; play.textContent = '▶︎'; }
    else { play.textContent = '❚❚'; state.playing = setInterval(() => render((state.i + 1) % state.dates.length), 850); }
  };
  document.getElementById('mode').onclick = e => {
    const b = e.target.closest('button'); if (!b) return;
    [...e.currentTarget.children].forEach(c => c.classList.toggle('on', c === b));
    state.renderMode = b.dataset.m;
    render(state.i);
  };
  document.getElementById('base').onclick = e => {
    const b = e.target.closest('button'); if (!b) return;
    [...e.currentTarget.children].forEach(c => c.classList.toggle('on', c === b));
    const sat = b.dataset.b === 'sat';
    if (sat !== baseIsSat) {
      baseIsSat = sat;
      sat ? (map.removeLayer(mapLayer), satLayer.addTo(map)) : (map.removeLayer(satLayer), mapLayer.addTo(map));
      document.body.classList.toggle('sat', sat);
    }
  };
  document.getElementById('zones').onchange = e => {
    state.zonesOn = e.target.checked;
    if (e.target.checked) state.zoneLayer.addTo(map); else map.removeLayer(state.zoneLayer);
  };
  document.getElementById('onlyCoded').onchange = e => {
    state.onlyCoded = e.target.checked;
    render(state.i);
  };
  document.getElementById('onlyActive').onchange = e => {
    state.onlyActive = e.target.checked;
    render(state.i);
  };
  window.addEventListener('keydown', e => {
    if (e.key === 'ArrowRight') render(Math.min(state.dates.length - 1, state.i + 1));
    if (e.key === 'ArrowLeft') render(Math.max(0, state.i - 1));
    if (e.key === ' ') { e.preventDefault(); play.click(); }
  });
}

boot();


/* ---------- about / evidence ---------- */
function bindModals() {
  const open = id => document.getElementById(id).classList.add('open');
  const closeAll = () => document.querySelectorAll('.modal').forEach(m => m.classList.remove('open'));
  document.getElementById('btnAbout').onclick = e => { e.preventDefault(); open('about'); };
  document.getElementById('btnEvidence').onclick = e => { e.preventDefault(); renderEvidence(); open('evidence'); };
  document.querySelectorAll('[data-close]').forEach(b => b.onclick = closeAll);
  document.querySelectorAll('.modal').forEach(m => m.onclick = e => { if (e.target === m) closeAll(); });
  window.addEventListener('keydown', e => { if (e.key === 'Escape') closeAll(); });
}

const KIND_LABEL = {
  'metal/contratos': 'metálicos · contratos', 'metal/solicitudes': 'metálicos · solicitudes',
  'metal/ambos': 'metálicos · ambos', 'nometal/contratos': 'no metálicos · contratos',
  'nometal/solicitudes': 'no metálicos · solicitudes', 'nometal/ambos': 'no metálicos · ambos'
};

function renderEvidence() {
  const date = state.dates[state.i] || '';
  document.getElementById('evDate').textContent = label(date);
  const host = document.getElementById('evList');
  host.innerHTML = '';
  let any = false;
  for (const [kind, name] of Object.entries(KIND_LABEL)) {
    const ev = state.evidence[date + '|' + kind];
    if (!ev) continue;
    if (!ev.boxes && !(ev.sheet && ev.sheet.url) && !(ev.table && ev.table.url)) continue;
    any = true;
    const bits = [`<b>${name}</b>`];
    const meta = [];
    meta.push(`${(ev.boxes || 0).toLocaleString('es')} recintos`);
    if (ev.coded) meta.push(`${ev.coded.toLocaleString('es')} con código`);
    if (ev.table) meta.push(`tabla: ${ev.table.rows} filas · ${ev.table.active} vigentes`);
    bits.push(`<span class="m">${meta.join(' · ')}</span>`);
    const links = [];
    if (ev.sheet && ev.sheet.url) {
      links.push(`<a href="${ev.sheet.url}" target="_blank" rel="noopener">hoja PDF</a>`);
      if (ev.sheet.wb) links.push(`<a href="${ev.sheet.wb}" target="_blank" rel="noopener">Wayback</a>`);
    }
    if (ev.table && ev.table.url) {
      links.push(`<a href="${ev.table.url}" target="_blank" rel="noopener">tabla LISTADO</a>`);
      if (ev.table.wb) links.push(`<a href="${ev.table.wb}" target="_blank" rel="noopener">Wayback</a>`);
    }
    if (ev.dwg && ev.dwg.length) {
      ev.dwg.forEach((f, i) => links.push(
        `<a href="${f.url}" target="_blank" rel="noopener">DWG${ev.dwg.length > 1 ? ' ' + (i + 1) : ''}</a>` +
        ` (<a href="${f.wb}" target="_blank" rel="noopener">WB</a>)`));
    }
    bits.push(links.join(' · '));
    const d = document.createElement('div');
    d.className = 'evrow';
    d.innerHTML = bits.join('<br>');
    host.appendChild(d);
  }
  for (const [kind, name] of Object.entries(KIND_LABEL)) {
    if (date + '|' + kind in state.evidence) continue;
    if (!state.boxes[date] || !state.boxes[date][kind]) continue;
    const d = document.createElement('div');
    d.className = 'evrow';
    d.innerHTML = `<b>${name}</b><br><span class="m">sin PDF indexado para este mes</span>`;
    host.appendChild(d);
    any = true;
  }
  if (!any) host.innerHTML = '<div class="evrow"><span class="m">Sin datos para este mes.</span></div>';
}
