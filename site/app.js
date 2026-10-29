'use strict';
const $ = id => document.getElementById(id);
const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const fmt = n => n == null ? '-' : Math.round(n).toLocaleString('ko-KR');
const pct = v => v == null ? '-' : (v * 100).toFixed(1) + '%';
const RAMP = ['#cde2fb', '#86b6ef', '#3987e5', '#1c5cab', '#0d366b'];  // sequential blue, light → dark = larger gap
const NODATA = '#d6d5d0';

// Every metric is a gap share (higher = worse) so the map always reads "darker = less served".
// v(x) takes an aggregate {area, pop, stops, known, few, bus, rail, either, good, goodArea} and returns 0..1 or null.
const METRICS = [
  { id: 'either', name: '버스·철도 도보권 밖 면적 비율', v: x => x.area ? 1 - x.either / x.area : null,
    note: m => `버스 정류장 ${m.bus_m}m, 철도역 ${m.rail_m / 1000}km(직선거리) 어디에도 들지 않는 면적의 비율입니다. 면적 기준이라 산지가 넓은 읍·면은 실제 생활권보다 나쁘게 보일 수 있습니다.` },
  { id: 'bus', name: `버스 정류장 도보권 밖 면적 비율`, v: x => x.area ? 1 - x.bus / x.area : null,
    note: m => `가장 가까운 버스 정류장까지 직선거리 ${m.bus_m}m가 넘는 면적의 비율입니다.` },
  { id: 'good', name: '노선이 넉넉한 정류장 도보권 밖 비율', v: x => x.goodArea ? 1 - x.good / x.goodArea : null,
    note: m => `정차 노선이 ${m.good_routes}개 이상인 정류장에서 ${m.bus_m}m가 넘는 면적의 비율입니다. 정류장은 있어도 노선이 1~${m.good_routes - 1}개뿐인 곳은 '밖'으로 셉니다. 정차 노선수 자료가 없는 시군구는 회색입니다.` },
  { id: 'few', name: `노선 2개 이하 정류장 비율`, v: x => x.known ? x.few / x.known : null,
    note: m => `정차 노선수가 확인된 정류장 가운데 노선이 ${m.good_routes - 1}개 이하인 정류장의 비율입니다(교통카드 자료 기준).` },
  { id: 'rail', name: '철도역 1km 밖 면적 비율', v: x => x.area ? 1 - x.rail / x.area : null,
    note: m => `도시철도·광역철도·일반철도·KTX 역에서 직선거리 ${m.rail_m / 1000}km가 넘는 면적의 비율입니다.` },
];

let D, C, GEO, T, U, SGGPOP, meta, map, sortSgg = { k: 'v', asc: false }, sortDong = { k: 'v', asc: false }, pickSgg = null;
const st = { metric: 'either', sido: '', urban: false };

function agg(rows) {
  const x = { area: 0, pop: 0, stops: 0, known: 0, few: 0, bus: 0, rail: 0, either: 0, good: 0, goodArea: 0, n: rows.length };
  for (const r of rows) {
    const a = r[C.area_km2];
    x.area += a; x.pop += r[C.pop] || 0; x.stops += r[C.stops]; x.known += r[C.stops_known]; x.few += r[C.stops_few];
    x.bus += a * r[C.bus500]; x.rail += a * r[C.rail1k]; x.either += a * r[C.either];
    if (r[C.good500] != null) { x.good += a * r[C.good500]; x.goodArea += a; }
  }
  return x;
}
const metric = () => METRICS.find(m => m.id === st.metric);
const visible = r => (!st.urban || r[C.type] === '동') && (!st.sido || r[C.sido] === st.sido);
const cls = v => v == null ? -1 : Math.min(4, Math.floor(v * 5));

async function main() {
  const [stats, geo] = await Promise.all([fetch('data/stats.json').then(r => r.json()), fetch('data/dongs.geojson').then(r => r.json())]);
  D = stats.rows; meta = stats.meta; T = stats.sgg_trips || {}; U = stats.sgg_urban || {}; C = Object.fromEntries(stats.cols.map((c, i) => [c, i]));
  SGGPOP = {};
  for (const r of D) SGGPOP[r[C.sgg]] = (SGGPOP[r[C.sgg]] || 0) + (r[C.pop] || 0);
  $('asof').textContent = `기준: 정류장 위치 ${meta.stops_collected} 수집 · 정차 노선수 ${meta.route_days.length ? meta.route_days.map(d => d.slice(0, 4) + '-' + d.slice(4, 6) + '-' + d.slice(6)).join(', ') + ' 운행일' : '수집 중'}${meta.upis_year ? ' · 도시계획현황 ' + meta.upis_year + '년' : ''}${meta.trips_months.length ? ' · 교통카드 통행 ' + meta.trips_months.map(m => m.slice(0, 4) + '년 ' + +m.slice(4) + '월').join(', ') : ''} · 인구 ${meta.pop_ym.slice(0, 4)}년 ${+meta.pop_ym.slice(4)}월 · 행정동 경계 ${meta.boundary.replace('ver', '')}`;
  for (const m of METRICS) $('metric').add(new Option(m.name, m.id));
  const sidos = [...new Map(D.map(r => [r[C.sido], r[C.sidonm]])).entries()].sort((a, b) => a[0].localeCompare(b[0]));
  for (const [c, n] of sidos) $('sido').add(new Option(n, c));
  $('metric').onchange = e => { st.metric = e.target.value; render(); };
  $('sido').onchange = e => { st.sido = e.target.value; pickSgg = null; render(); zoomTo(D.filter(r => !st.sido || r[C.sido] === st.sido)); };
  $('urban').onchange = e => { st.urban = e.target.checked; render(); };
  GEO = geo;
  initMap(geo);
  render();
}

function initMap(geo) {
  if (typeof maplibregl === 'undefined') { $('map').innerHTML = '<p class="note" style="padding:16px">지도 라이브러리를 불러오지 못했습니다. 새로고침해 주세요.</p>'; return; }
  map = new maplibregl.Map({ container: 'map', style: 'https://tiles.openfreemap.org/styles/positron', center: [127.8, 36.2], zoom: 6, attributionControl: { compact: true } });
  map.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'top-right');
  map.on('load', async () => {
    map.addSource('dongs', { type: 'geojson', data: geo });
    const before = map.getStyle().layers.find(l => l.type === 'symbol')?.id;
    map.addLayer({ id: 'dong-fill', type: 'fill', source: 'dongs', paint: {
      'fill-color': ['match', ['coalesce', ['feature-state', 'c'], -1], 0, RAMP[0], 1, RAMP[1], 2, RAMP[2], 3, RAMP[3], 4, RAMP[4], NODATA],
      'fill-opacity': ['case', ['boolean', ['feature-state', 'hide'], false], 0.08, 0.72] } }, before);
    map.addLayer({ id: 'dong-line', type: 'line', source: 'dongs', minzoom: 8, paint: { 'line-color': '#ffffff', 'line-width': 0.5, 'line-opacity': 0.7 } }, before);
    paintMap();
    map.on('click', 'dong-fill', e => {
      const r = D[e.features[0].id];
      if (!map.queryRenderedFeatures(e.point, { layers: ['stops', 'rail'].filter(l => map.getLayer(l)) }).length)
        new maplibregl.Popup({ maxWidth: '300px' }).setLngLat(e.lngLat).setHTML(dongPopup(r)).addTo(map);
    });
    map.on('mouseenter', 'dong-fill', () => { map.getCanvas().style.cursor = 'pointer'; });
    map.on('mouseleave', 'dong-fill', () => { map.getCanvas().style.cursor = ''; });
    const [stops, rail] = await Promise.all([fetch('data/stops.json').then(r => r.json()), fetch('data/stations.json').then(r => r.json())]);
    map.addSource('stops', { type: 'geojson', data: { type: 'FeatureCollection', features: stops.map(s => ({ type: 'Feature', properties: { r: s[2], o: s[3] }, geometry: { type: 'Point', coordinates: [s[0], s[1]] } })) } });
    map.addLayer({ id: 'stops', type: 'circle', source: 'stops', minzoom: 10, paint: {
      'circle-radius': ['interpolate', ['linear'], ['zoom'], 10, 2, 15, 5],
      'circle-color': ['case', ['<', ['get', 'r'], 0], '#a3a29c', ['<', ['get', 'r'], meta.good_routes], '#eb6834', '#52514e'],
      'circle-stroke-color': '#ffffff', 'circle-stroke-width': ['interpolate', ['linear'], ['zoom'], 10, 0, 14, 1] } });
    map.addSource('rail', { type: 'geojson', data: { type: 'FeatureCollection', features: rail.map(s => ({ type: 'Feature', properties: { n: s[2] }, geometry: { type: 'Point', coordinates: [s[0], s[1]] } })) } });
    map.addLayer({ id: 'rail', type: 'circle', source: 'rail', minzoom: 7, paint: {
      'circle-radius': ['interpolate', ['linear'], ['zoom'], 7, 2.5, 14, 7], 'circle-color': '#6250d6', 'circle-stroke-color': '#ffffff', 'circle-stroke-width': 1.5 } });
    map.on('click', 'stops', e => {
      const p = e.features[0].properties;
      new maplibregl.Popup({ maxWidth: '240px' }).setLngLat(e.lngLat).setHTML(`<b>버스 정류장</b><br>정차 노선 ${p.r < 0 ? '자료 없음' : p.r + '개'}${p.o ? '<br><small>위치: OpenStreetMap (국토부 파일에 없는 지역)</small>' : ''}`).addTo(map);
    });
    map.on('click', 'rail', e => new maplibregl.Popup({ maxWidth: '240px' }).setLngLat(e.lngLat).setHTML(`<b>${esc(e.features[0].properties.n)}</b><br>철도역`).addTo(map));
    for (const [id, layer] of [['show-stops', 'stops'], ['show-rail', 'rail']]) {
      const set = () => map.setLayoutProperty(layer, 'visibility', $(id).checked ? 'visible' : 'none');
      $(id).onchange = set; set();
    }
  });
}

function paintMap() {
  if (!map || !map.getSource('dongs')) return;
  const m = metric();
  D.forEach((r, i) => map.setFeatureState({ source: 'dongs', id: i }, { c: cls(m.v(agg([r]))), hide: !visible(r) }));
}

function dongPopup(r) {
  const x = agg([r]);
  const line = (k, v) => `<tr><td>${k}</td><td style="text-align:right">${v}</td></tr>`;
  return `<b>${esc(r[C.sidonm])} ${esc(r[C.sggnm])} ${esc(r[C.name])}</b> <small>(${r[C.type]})</small><table>` +
    line('주민등록인구', fmt(r[C.pop])) + line('면적', r[C.area_km2].toFixed(2) + '㎢') + line('버스 정류장', fmt(r[C.stops]) + '곳') +
    METRICS.map(m => line(m.name, pct(m.v(x)))).join('') + (U[r[C.sgg]] ? line(`법정 도시지역 면적 (${U[r[C.sgg]].city ? esc(U[r[C.sgg]].city) + ' 전체' : '시군구'})`, pct(U[r[C.sgg]].area)) : '') + (() => { const t = trips(r[C.sgg]); return t.trip == null ? '' :
      line('주민 1인당 하루 승차 (시군구)', t.trip.toFixed(2)) + line('환승 통행 비중 (시군구)', pct(t.transfer)); })() + '</table>' +
    (r[C.osm_fill] ? '<small>이 시군구는 국토부 정류장 파일에 거의 없어 OpenStreetMap 정류장으로 보완했습니다.</small><br>' : '') +
    (r[C.route_ok] ? '' : '<small>이 시군구는 정차 노선수 자료가 없거나 정류장 연결이 부족합니다.</small>');
}

function zoomTo(rows) {
  if (!map || !rows.length) return;
  let b = null;
  const idx = new Set(rows.map(r => D.indexOf(r)));
  for (const f of GEO.features) {
    if (!idx.has(f.id)) continue;
    const walk = c => typeof c[0] === 'number' ? (b = b ? [Math.min(b[0], c[0]), Math.min(b[1], c[1]), Math.max(b[2], c[0]), Math.max(b[3], c[1])] : [c[0], c[1], c[0], c[1]]) : c.forEach(walk);
    walk(f.geometry.coordinates);
  }
  if (b) map.fitBounds([[b[0], b[1]], [b[2], b[3]]], { padding: 30, duration: 600 });
}

function render() {
  const m = metric();
  $('metric-note').textContent = m.note(meta);
  const rows = D.filter(visible);
  const x = agg(rows);
  $('summary').innerHTML = `<b>${esc(st.sido ? rows[0]?.[C.sidonm] ?? '' : '전국')}${st.urban ? ' 동 지역' : ''}</b>: 행정동 ${fmt(x.n)}곳 · 인구 ${fmt(x.pop)}명 · 면적 ${fmt(x.area)}㎢ · 버스 정류장 ${fmt(x.stops)}곳 · ${esc(m.name)} <b>${pct(m.v(x))}</b>`;
  legend(m);
  paintMap();
  renderSgg(rows, m);
  renderDongs(rows, m);
}

function legend(m) {
  const lab = ['0~20%', '20~40%', '40~60%', '60~80%', '80~100%'];
  $('legend').innerHTML = `<div class="t">${esc(m.name)}</div>` + RAMP.map((c, i) => `<div class="row"><i style="background:${c}"></i>${lab[i]}</div>`).join('') +
    `<div class="row"><i style="background:${NODATA}"></i>자료 없음</div>` +
    `<div class="row" style="margin-top:4px"><i class="pt" style="background:#eb6834"></i>정류장(노선 ${meta.good_routes - 1}개 이하)</div>` +
    `<div class="row"><i class="pt" style="background:#52514e"></i>정류장(노선 ${meta.good_routes}개 이상)</div>` +
    `<div class="row"><i class="pt" style="background:#a3a29c"></i>정류장(노선 수 자료 없음)</div>` +
    `<div class="row"><i class="pt" style="background:#6250d6;border:1.5px solid #fff;outline:1px solid #6250d6"></i>철도역</div>` +
    `<div class="row"><small>정류장은 확대(줌 10 이상)하면 보입니다.</small></div>`;
}

function sgRows(rows, m) {
  const by = new Map();
  for (const r of rows) {
    const k = r[C.sgg];
    if (!by.has(k)) by.set(k, []);
    by.get(k).push(r);
  }
  return [...by.values()].map(rs => {
    const x = agg(rs);
    return { sgg: rs[0][C.sgg], name: `${rs[0][C.sidonm]} ${rs[0][C.sggnm]}`, pop: x.pop, area: x.area, stops: x.stops,
      v: m.v(x), either: METRICS[0].v(x), few: METRICS[3].v(x), route: rs[0][C.route_ok], osm: rs[0][C.osm_fill], ...trips(rs[0][C.sgg]), uarea: U[rs[0][C.sgg]]?.area ?? null, upop: U[rs[0][C.sgg]]?.pop ?? null, ucity: U[rs[0][C.sgg]]?.city ?? null };
  });
}

// 교통카드 trips are per whole 시군구 (they do not change with the 동 지역 filter)
function trips(sgg) {
  const t = T[sgg], pop = SGGPOP[sgg];
  if (!t) return { trip: null, transfer: null, elder: null };
  const users = Object.values(t.users).reduce((a, b) => a + b, 0);
  return { trip: pop ? t.day / pop : null, transfer: t.transfer != null && t.day ? t.transfer / t.day : null,
    elder: users && t.users['경로'] != null ? t.users['경로'] / users : null };
}

function table(el, cols, data, sort, onSort, onRow) {
  const s = [...data].sort((a, b) => {
    const p = a[sort.k], q = b[sort.k];
    if (p == null && q == null) return 0;
    if (p == null) return 1;
    if (q == null) return -1;
    return (typeof p === 'string' ? p.localeCompare(q) : p - q) * (sort.asc ? 1 : -1);
  });
  el.innerHTML = '<thead><tr>' + cols.map(c => `<th data-k="${c.k}" class="${c.l ? 'l ' : ''}${sort.k === c.k ? 'on' + (sort.asc ? ' asc' : '') : ''}">${c.h}</th>`).join('') + '</tr></thead><tbody>' +
    s.slice(0, 500).map((r, i) => `<tr data-i="${i}">` + cols.map(c => { const v = c.f ? c.f(r[c.k], r) : r[c.k]; return `<td class="${c.l ? 'l' : ''}${r[c.k] == null ? ' na' : ''}">${v}</td>`; }).join('') + '</tr>').join('') + '</tbody>';
  el.querySelectorAll('th').forEach(th => th.onclick = () => onSort(th.dataset.k));
  if (onRow) el.querySelectorAll('tbody tr').forEach(tr => tr.onclick = () => onRow(s[+tr.dataset.i]));
  return s;
}

let sggShown = [], dongShown = [];
function renderSgg(rows, m) {
  $('sgg-title').textContent = `시군구 순위 · ${m.name}`;
  const cols = [{ k: 'name', h: '시군구', l: 1, f: (v, r) => esc(v) + (r.osm ? ' <small title="OpenStreetMap 정류장으로 보완">*</small>' : '') },
    { k: 'v', h: m.name, f: pct }, { k: 'pop', h: '인구', f: fmt }, { k: 'area', h: '면적(㎢)', f: fmt }, { k: 'stops', h: '정류장', f: fmt },
    { k: 'either', h: '버스·철도 도보권 밖', f: pct }, { k: 'few', h: '노선 2개 이하 정류장', f: pct },
    { k: 'uarea', h: '법정 도시지역 면적', f: (v, r) => pct(v) + (r.ucity && v != null ? ` <small title="${esc(r.ucity)} 전체 값">시</small>` : '') },
    { k: 'upop', h: '도시지역 거주 인구', f: pct },
    { k: 'trip', h: '주민 1인당 하루 승차', f: v => v == null ? '-' : v.toFixed(2) }, { k: 'transfer', h: '환승 통행 비중', f: pct }, { k: 'elder', h: '경로 승차 비중', f: pct }];
  sggShown = table($('sgg-table'), cols, sgRows(rows, m), sortSgg, k => { sortSgg = { k, asc: sortSgg.k === k ? !sortSgg.asc : k === 'name' }; render(); },
    r => { pickSgg = r.sgg; renderDongs(D.filter(visible), m); zoomTo(D.filter(d => d[C.sgg] === r.sgg)); $('dong-title').scrollIntoView({ behavior: 'smooth' }); });
  $('sgg-csv').onclick = () => csv(`시군구_${st.metric}.csv`, ['시군구코드', '시군구', m.name, '인구', '면적_km2', '정류장', '버스철도도보권밖', '노선2개이하정류장비율', '법정도시지역면적비율', '도시지역거주인구비율', '주민1인당하루승차', '환승통행비중', '경로승차비중', '노선수자료', 'OSM보완'],
    sggShown.map(r => [r.sgg, r.name, r.v, r.pop, r.area.toFixed(3), r.stops, r.either, r.few, r.uarea, r.upop, r.trip, r.transfer, r.elder, r.route, r.osm]));
}

function renderDongs(rows, m) {
  const pick = pickSgg ? rows.filter(r => r[C.sgg] === pickSgg) : rows;
  const label = pickSgg ? `${pick[0]?.[C.sidonm] ?? ''} ${pick[0]?.[C.sggnm] ?? ''}` : (st.sido ? rows[0]?.[C.sidonm] : '전국');
  $('dong-title').textContent = `행정동 · ${label}${pickSgg ? '' : ' (상위 500곳)'}`;
  const data = pick.map(r => { const x = agg([r]); return { code: r[C.code], name: r[C.name], sgg: `${r[C.sidonm]} ${r[C.sggnm]}`, type: r[C.type], pop: r[C.pop], area: r[C.area_km2], stops: r[C.stops], v: m.v(x), either: METRICS[0].v(x), few: METRICS[3].v(x), i: D.indexOf(r) }; });
  const cols = [{ k: 'name', h: '행정동', l: 1, f: esc }, { k: 'sgg', h: '시군구', l: 1, f: esc }, { k: 'type', h: '구분', l: 1 }, { k: 'v', h: m.name, f: pct },
    { k: 'pop', h: '인구', f: fmt }, { k: 'area', h: '면적(㎢)', f: v => v.toFixed(2) }, { k: 'stops', h: '정류장', f: fmt }, { k: 'either', h: '버스·철도 도보권 밖', f: pct }, { k: 'few', h: '노선 2개 이하 정류장', f: pct }];
  dongShown = table($('dong-table'), cols, data, sortDong, k => { sortDong = { k, asc: sortDong.k === k ? !sortDong.asc : ['name', 'sgg', 'type'].includes(k) }; renderDongs(D.filter(visible), metric()); },
    r => { zoomTo([D[r.i]]); window.scrollTo({ top: $('map').offsetTop - 10, behavior: 'smooth' }); });
  $('dong-csv').onclick = () => csv(`행정동_${st.metric}.csv`, ['행정동코드', '행정동', '시군구', '구분', m.name, '인구', '면적_km2', '정류장', '버스철도도보권밖', '노선2개이하정류장비율'],
    dongShown.map(r => [r.code, r.name, r.sgg, r.type, r.v, r.pop, r.area, r.stops, r.either, r.few]));
}

function csv(name, head, rows) {
  const q = v => v == null ? '' : /[",\n]/.test(String(v)) ? `"${String(v).replace(/"/g, '""')}"` : v;
  const blob = new Blob(['﻿' + [head, ...rows].map(r => r.map(q).join(',')).join('\n')], { type: 'text/csv' });
  const a = Object.assign(document.createElement('a'), { href: URL.createObjectURL(blob), download: name });
  a.click(); URL.revokeObjectURL(a.href);
}

main().catch(e => { $('summary').textContent = '자료를 불러오지 못했습니다: ' + e.message; console.error(e); });
