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
  active: new Set(CATS.map(c => c[0])), layer: null
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
  const [boxes, sheets] = await Promise.all([
    fetch('boxes.json').then(r => r.json()).catch(() => ({})),
    fetch('sheets.json').then(r => r.json()).catch(() => ({})),
  ]);
  state.boxes = boxes; state.sheets = sheets;
  state.dates = Object.keys(boxes).sort();
  buildChips(); buildYears(); bind();
  const sl = document.getElementById('slider');
  sl.max = Math.max(0, state.dates.length - 1);
  render(state.dates.length - 1);
  map.invalidateSize();
  map.fitBounds([[7.05, -83.4], [9.85, -77.0]], { padding: [12, 12] });
  window.addEventListener('resize', () => map.invalidateSize());
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
  let n = 0;
  const by = state.boxes[date] || {};
  for (const [kind, arr] of Object.entries(by)) {
    if (!state.active.has(kind)) continue;
    const col = COLOR[kind] || '#fff';
    const name = (CATS.find(c => c[0] === kind) || [0, kind])[1];
    for (const [w, s, e, t] of arr) {
      L.rectangle([[s, w], [t, e]], {
        renderer: boxRenderer, color: col, weight: 1, opacity: .9,
        fillColor: col, fillOpacity: .16
      }).bindPopup(
        `<div class="tt"><b>${name}</b><br>${((e - w) * 104).toFixed(1)} × ${((t - s) * 110).toFixed(1)} km` +
        `<br><span style="color:#8b96a5">${s.toFixed(3)}, ${w.toFixed(3)}</span></div>`,
        { closeButton: false }).addTo(g);
      n++;
    }
  }
  state.layer = g.addTo(map);

  const sh = state.sheets[date] && Object.values(state.sheets[date])[0];
  document.getElementById('stat').innerHTML = n
    ? `· ${n.toLocaleString('es')} recintos`
    : '· sin datos';
  document.getElementById('src').innerHTML = sh && sh.url
    ? `<a href="${sh.url}" target="_blank" rel="noopener">${sh.src === 'live' ? 'mici.gob.pa' : 'Wayback'}</a>` : '';
}

function bind() {
  document.getElementById('slider').oninput = e => render(+e.target.value);
  const play = document.getElementById('play');
  play.onclick = () => {
    if (state.playing) { clearInterval(state.playing); state.playing = null; play.textContent = '▶︎'; }
    else { play.textContent = '❚❚'; state.playing = setInterval(() => render((state.i + 1) % state.dates.length), 850); }
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
  window.addEventListener('keydown', e => {
    if (e.key === 'ArrowRight') render(Math.min(state.dates.length - 1, state.i + 1));
    if (e.key === 'ArrowLeft') render(Math.max(0, state.i - 1));
    if (e.key === ' ') { e.preventDefault(); play.click(); }
  });
}

boot();
