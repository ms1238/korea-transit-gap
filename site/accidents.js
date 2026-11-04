'use strict';
// cache-busting: the deploy stamps this script's URL with ?v=<commit>; the data files get the same stamp
const DV = (document.currentScript?.src.match(/[?&]v=([\w-]+)/) || [])[1];
const dv = u => DV ? `${u}?v=${DV}` : u;
// PM 교통사고 합성데이터 (도로교통공단): one compact row per synthetic record, units of current 시군구 (see build.py).
const $ = id => document.getElementById(id);
const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const fmt = n => n == null ? '-' : Math.round(n).toLocaleString('ko-KR');
const pct = v => v == null ? '-' : (v * 100).toFixed(1) + '%';
const RAMP = ['#fde3d0', '#f9b98f', '#f08a4f', '#d4572a', '#9c3417'];  // sequential orange, light → dark = more
const NONE = '#e4e3df';
const NARROW = window.matchMedia('(max-width: 640px)').matches;
const METRICS = {
  n: { name: '기록 수', v: x => x.n },
  pc: { name: '인구 10만 명당 기록 수', v: x => x.pop ? x.n / x.pop * 1e5 : null, d: 1 },
  cas: { name: '사상자 수', v: x => x.dead + x.serious + x.minor + x.report },
  ks: { name: '사망·중상자 수', v: x => x.dead + x.serious },
};
const ORDER = {  // fixed category orders (time and age read in their natural order)
  time: Array.from({ length: 12 }, (_, i) => `${String(i * 2).padStart(2, '0')}시-${String(i * 2 + 2).padStart(2, '0')}시`),
  age: ['10-14세', '15-19세', '20-24세', '25-29세', '30-34세', '35-39세', '40-44세', '45-49세', '50-54세', '55-59세', '60-64세', '65-69세', '70세이상', '불명'],
  sex: ['남', '여', '기타불명'],
};
let A, C, U, D, SCI, GEO, map, sort = { k: 'v', asc: false }, shown = [];
const st = { metric: 'n', sido: '', unit: '' };
let unitOf = {};  // dong index → unit index

async function main() {
  const [acc, stats, geo] = await Promise.all(['data/accidents.json', 'data/stats.json', 'data/dongs.geojson'].map(u => fetch(dv(u)).then(r => r.json())));
  A = acc; U = acc.units; D = stats.rows; GEO = geo;
  C = Object.fromEntries(acc.cols.map((c, i) => [c, i]));
  const SC = SCI = Object.fromEntries(stats.cols.map((c, i) => [c, i]));
  const sggUnit = {};
  U.forEach((u, i) => { u.sido = null; for (const g of u.sgg) sggUnit[g] = i; });
  D.forEach((r, i) => { const k = sggUnit[r[SC.sgg]]; if (k != null) { unitOf[i] = k; U[k].sido ??= r[SC.sido]; U[k].sidonm ??= r[SC.sidonm]; } });
  const d = acc.meta.date;
  $('asof').textContent = `${acc.meta.title || ''} · 공개본 기준일 ${d ? d.slice(0, 4) + '-' + d.slice(4, 6) + '-' + d.slice(6) : '-'} · ${fmt(acc.meta.n)}건 (기록이 다루는 기간은 자료에 적혀 있지 않습니다)`;
  for (const [c, n] of [...new Map(U.map(u => [u.sido, u.sidonm])).entries()].sort((a, b) => a[0].localeCompare(b[0]))) $('sido').add(new Option(n, c));
  $('metric').onchange = e => { st.metric = e.target.value; render(); };
  $('sido').onchange = e => { st.sido = e.target.value; st.unit = ''; fillUnits(); render(); zoom(); };
  $('unit').onchange = e => { st.unit = e.target.value; render(); zoom(); };
  fillUnits();
  const showLegend = on => { $('legend').hidden = !on; $('legend-btn').hidden = on; };
  $('legend-btn').onclick = () => showLegend(true);
  $('legend').onclick = e => { if (e.target.closest('.legend-x')) showLegend(false); };
  showLegend(!NARROW);
  initMap();
  render();
}

const scopeRows = () => A.rows.filter(r => st.unit !== '' ? r[C.unit] === +st.unit : !st.sido || U[r[C.unit]].sido === st.sido);
// the 시군구 list follows the 시도 (all of them, by 시도 then name, when 전국)
function fillUnits() {
  const sel = $('unit'), sidoName = Object.fromEntries([...$('sido').options].map(o => [o.value, o.text]));
  sel.length = 1;
  U.map((u, i) => ({ u, i })).filter(({ u }) => u.sido && (!st.sido || u.sido === st.sido))
    .sort((a, b) => a.u.sido.localeCompare(b.u.sido) || a.u.name.localeCompare(b.u.name, 'ko'))
    .forEach(({ u, i }) => sel.add(new Option(st.sido ? u.name.replace(/^\S+ /, '') : u.name, i)));
  sel.value = st.unit;
}
function pick(k) {  // a 시군구 picked on the map: its 시도 and itself in the selects
  if (k == null) return;
  if (st.sido !== U[k].sido) { st.sido = U[k].sido; $('sido').value = st.sido; }
  st.unit = String(k); fillUnits(); render();
}
function agg(rows) {
  const x = { n: rows.length, dead: 0, serious: 0, minor: 0, report: 0 };
  for (const r of rows) { x.dead += r[C.dead]; x.serious += r[C.serious]; x.minor += r[C.minor]; x.report += r[C.report]; }
  return x;
}
function perUnit() {
  const by = U.map((u, i) => ({ i, name: u.name, pop: u.pop, sido: u.sido, n: 0, dead: 0, serious: 0, minor: 0, report: 0 }));
  for (const r of A.rows) { const b = by[r[C.unit]]; b.n++; b.dead += r[C.dead]; b.serious += r[C.serious]; b.minor += r[C.minor]; b.report += r[C.report]; }
  for (const b of by) b.v = METRICS[st.metric].v(b);
  return by;
}

function render() {
  const rows = scopeRows(), x = agg(rows), m = METRICS[st.metric];
  const where = st.unit !== '' ? U[+st.unit].name : st.sido ? $('sido').selectedOptions[0].text : '전국';
  $('kpis').innerHTML = `<div class="kpi"><div class="kt">범위</div><div class="kv" style="font-size:16px">${esc(where)}</div></div>` + [['기록', x.n], ['사망자', x.dead], ['중상자', x.serious], ['경상자', x.minor], ['부상신고자', x.report]]
    .map(([t, v]) => `<div class="kpi"><div class="kt">${t}</div><div class="kv">${fmt(v)}</div></div>`).join('');
  bars('c-type', rows, C.type, null);
  bars('c-time', rows, C.time, ORDER.time);
  bars('c-age', rows, C.age, ORDER.age);
  bars('c-sex', rows, C.sex, ORDER.sex);
  const units = perUnit();
  paint(units, m);
  table(units.filter(u => (!st.sido || u.sido === st.sido) && u.n), m);
}

// horizontal bars, one series: the category, a bar, the count (share on hover)
function bars(id, rows, col, order) {
  const c = {};
  for (const r of rows) c[r[col]] = (c[r[col]] || 0) + 1;
  const keys = order ? order.filter(k => c[k]) : Object.keys(c).sort((a, b) => c[b] - c[a]);
  const max = Math.max(1, ...keys.map(k => c[k]));
  $(id).innerHTML = keys.map(k => `<div class="bar" title="${esc(k)}: ${fmt(c[k])}건 (${pct(c[k] / rows.length)})"><span class="bl">${esc(k)}</span>` +
    `<span class="bt"><i style="width:${(c[k] / max * 100).toFixed(1)}%"></i></span><span class="bv">${fmt(c[k])}</span></div>`).join('') || '<p class="note">기록 없음</p>';
}

// map: quintile classes of the metric over the units with records (national, so colours keep their meaning across 시도)
let breaks = [];
function paint(units, m) {
  const vals = units.filter(u => u.n).map(u => u.v).sort((a, b) => a - b);
  breaks = [0.2, 0.4, 0.6, 0.8].map(q => vals[Math.min(vals.length - 1, Math.floor(q * vals.length))]);
  legend(m);
  if (!map || !map.getSource('dongs')) return;
  D.forEach((_, i) => {
    const u = units[unitOf[i]];
    const k = u && u.n ? breaks.filter(b => u.v > b).length : -1;
    map.setFeatureState({ source: 'dongs', id: i }, { c: k, hide: st.unit !== '' ? unitOf[i] !== +st.unit : !!st.sido && D[i][2] !== st.sido });  // column 2: 시도 code
  });
}
function legend(m) {
  const f = v => m.d ? v.toFixed(1) : fmt(v);
  const lab = [`${f(breaks[0])} 이하`, ...[1, 2, 3].map(i => `${f(breaks[i - 1])}~${f(breaks[i])}`), `${f(breaks[3])} 초과`];
  $('legend').innerHTML = `<div class="t"><span>${esc(m.name)}</span><button class="legend-x" type="button" aria-label="범례 닫기">×</button></div>` +
    RAMP.map((c, i) => `<div class="row"><i style="background:${c}"></i>${lab[i]}</div>`).join('') +
    `<div class="row"><i style="background:${NONE}"></i>기록 없음</div><div class="row"><small>합성데이터: 경향 비교용</small></div>` + Beam.legendRows() + Young.legendRows();
}

function initMap() {
  if (typeof maplibregl === 'undefined') { $('map').innerHTML = '<p class="note" style="padding:16px">지도 라이브러리를 불러오지 못했습니다.</p>'; return; }
  map = new maplibregl.Map({ container: 'map', style: 'https://tiles.openfreemap.org/styles/positron', center: [127.8, 36.2], zoom: 6, attributionControl: { compact: true } });
  map.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'top-right');
  map.on('load', () => {
    map.addSource('dongs', { type: 'geojson', data: GEO });
    const before = map.getStyle().layers.find(l => l.type === 'symbol')?.id;
    map.addLayer({ id: 'fill', type: 'fill', source: 'dongs', paint: {
      'fill-color': ['match', ['coalesce', ['feature-state', 'c'], -1], 0, RAMP[0], 1, RAMP[1], 2, RAMP[2], 3, RAMP[3], 4, RAMP[4], NONE],
      'fill-opacity': ['case', ['boolean', ['feature-state', 'hide'], false], 0.08, 0.8] } }, before);
    render();
    Beam.add(map, () => legend(METRICS[st.metric]));
    Young.init(map, D, SCI, () => legend(METRICS[st.metric]));
    map.on('click', 'fill', e => {
      const k = unitOf[e.features[0].id], u = k != null ? perUnit()[k] : null;
      const bk = k != null && U[k].sgg.map(g => Beam.kind(g)).find(Boolean);
      const html = u ? `<b>${esc(u.name)}</b> <small>(합성데이터)</small>${bk ? `<br><small>빔모빌리티 ${bk}</small>` : ''}<table>` + [['기록', u.n], ['인구 10만 명당', u.pop ? (u.n / u.pop * 1e5).toFixed(1) : '-'], ['사망 · 중상', `${u.dead} · ${u.serious}`], ['경상 · 부상신고', `${u.minor} · ${u.report}`]]
        .map(([a, b]) => `<tr><td>${a}</td><td style="text-align:right">${typeof b === 'number' ? fmt(b) : b}</td></tr>`).join('') + '</table>' : '기록 없음';
      new maplibregl.Popup({ maxWidth: '260px' }).setLngLat(e.lngLat).setHTML(html).addTo(map);
      pick(k);
    });
  });
}
function zoom() {
  if (!map) return;
  let b = null;
  GEO.features.forEach((f, i) => {
    if (st.unit !== '' ? unitOf[i] !== +st.unit : st.sido && D[i][2] !== st.sido) return;
    const walk = c => typeof c[0] === 'number' ? (b = b ? [Math.min(b[0], c[0]), Math.min(b[1], c[1]), Math.max(b[2], c[0]), Math.max(b[3], c[1])] : [c[0], c[1], c[0], c[1]]) : c.forEach(walk);
    walk(f.geometry.coordinates);
  });
  if (b) map.fitBounds([[b[0], b[1]], [b[2], b[3]]], { padding: 30, duration: 600 });
}

function table(units, m) {
  $('tbl-title').textContent = `지역별 · ${m.name}`;
  const cols = [{ k: 'name', h: '지역', l: 1 }, { k: 'v', h: m.name, f: v => v == null ? '-' : m.d ? v.toFixed(1) : fmt(v) }, { k: 'n', h: '기록' }, { k: 'pop', h: '인구' },
    { k: 'dead', h: '사망' }, { k: 'serious', h: '중상' }, { k: 'minor', h: '경상' }, { k: 'report', h: '부상신고' }];
  shown = [...units].sort((a, b) => { const p = a[sort.k], q = b[sort.k]; return (p == null) - (q == null) || (typeof p === 'string' ? p.localeCompare(q) : p - q) * (sort.asc ? 1 : -1); });
  $('table').innerHTML = '<thead><tr>' + cols.map(c => `<th data-k="${c.k}" class="${c.l ? 'l ' : ''}${sort.k === c.k ? 'on' + (sort.asc ? ' asc' : '') : ''}">${c.h}</th>`).join('') + '</tr></thead><tbody>' +
    shown.map(u => '<tr>' + cols.map(c => `<td class="${c.l ? 'l' : ''}">${c.f ? c.f(u[c.k]) : c.l ? esc(u[c.k]) : fmt(u[c.k])}</td>`).join('') + '</tr>').join('') + '</tbody>';
  $('table').querySelectorAll('th').forEach(th => th.onclick = () => { sort = { k: th.dataset.k, asc: sort.k === th.dataset.k ? !sort.asc : th.dataset.k === 'name' }; render(); });
  $('csv').onclick = () => {
    const q = v => v == null ? '' : /[",\n]/.test(String(v)) ? `"${String(v).replace(/"/g, '""')}"` : v;
    const lines = [['지역', '기록', '인구', '인구10만명당', '사망', '중상', '경상', '부상신고'], ...shown.map(u => [u.name, u.n, u.pop, u.pop ? (u.n / u.pop * 1e5).toFixed(2) : '', u.dead, u.serious, u.minor, u.report])];
    const a = Object.assign(document.createElement('a'), { href: URL.createObjectURL(new Blob(['﻿' + lines.map(r => r.map(q).join(',')).join('\n')], { type: 'text/csv' })), download: 'PM사고_합성데이터_지역별.csv' });
    a.click(); URL.revokeObjectURL(a.href);
  };
}

main().catch(e => { $('kpis').textContent = '자료를 불러오지 못했습니다: ' + e.message; console.error(e); });
