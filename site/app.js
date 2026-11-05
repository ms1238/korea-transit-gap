'use strict';
// cache-busting: the deploy stamps this script's URL with ?v=<commit>; the data files get the same stamp
const DV = (document.currentScript?.src.match(/[?&]v=([\w-]+)/) || [])[1];
const dv = u => DV ? `${u}?v=${DV}` : u;
const $ = id => document.getElementById(id);
const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const fmt = n => n == null ? '-' : Math.round(n).toLocaleString('ko-KR');
const pct = v => v == null ? '-' : (v * 100).toFixed(1) + '%';
const RAMP = ['#cde2fb', '#86b6ef', '#3987e5', '#1c5cab', '#0d366b'];  // sequential blue, light → dark = larger gap
const NODATA = '#d6d5d0';
// Elevation: Mapzen Terrain Tiles on AWS Open Data (terrarium encoding, public, CORS open, no key)
const DEM = { type: 'raster-dem', tiles: ['https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png'], encoding: 'terrarium', tileSize: 256, maxzoom: 14,
  attribution: '<a href="https://github.com/tilezen/joerd/blob/master/docs/attribution.md" target="_blank">지형: Mapzen Terrain Tiles</a>' };

// Every metric is a gap share (higher = worse) so the map always reads "darker = less served".
// v(x) takes an aggregate of agg() and returns 0..1 or null. Area shares follow the basis toggle: 생활권 land (산림·수면 제외,
// the h_ columns weighted by 생활권 area) or the whole area.
const METRICS = [
  { id: 'either', name: '버스·철도 도보권 밖 면적 비율', v: x => x.busArea ? 1 - x.either / x.busArea : null,
    note: m => `버스 정류장 ${m.bus_m}m, 철도역 ${m.rail_m}m(직선거리) 어디에도 들지 않는 면적의 비율입니다.` + (st.hab ? '' : ' 전체 면적 기준이라 산지가 넓은 읍·면은 실제 생활권보다 훨씬 나쁘게 보입니다.') },
  { id: 'bus', name: `버스 정류장 도보권 밖 면적 비율`, v: x => x.busArea ? 1 - x.bus / x.busArea : null,
    note: m => `가장 가까운 버스 정류장까지 직선거리 ${m.bus_m}m가 넘는 면적의 비율입니다.` },
  { id: 'good', name: '노선 넉넉한 정류장 도보권 밖 면적 비율', v: x => x.goodArea ? 1 - x.good / x.goodArea : null,
    note: m => `정차 노선이 ${m.good_routes}개 이상인 정류장에서 ${m.bus_m}m가 넘는 면적의 비율입니다. 정류장은 있어도 노선이 1~${m.good_routes - 1}개뿐인 곳은 '밖'으로 셉니다. 이름이 정차 노선수 자료와 연결되지 않은 정류장은 노선이 넉넉한 것으로 봅니다(연결률이 낮은 시군구가 소외지역처럼 보이지 않도록). 정차 노선수 자료가 없는 시군구는 회색입니다.` },
  { id: 'pm', name: 'PM 10분 안에 새로 닿는 면적 비율', good: 1, v: x => x.pmArea ? (x.pm5 + x.pm10) / x.pmArea : null,
    note: m => `걸어서는 버스 정류장(노선 ${m.good_routes}개 이상, 노선 수를 모르는 곳은 모든 정류장) ${m.bus_m}m·철도역 ${m.rail_m}m 밖이지만, PM으로 10분(평균 ${m.pm_speed}km/h, 도로 우회 ${m.pm_detour}배 가정 → 직선 ${(m.pm10_m / 1000).toFixed(1)}km) 안에 그 정류장·역에 닿는 면적의 비율입니다. 높을수록 PM이 첫·마지막 구간을 메울 여지가 큽니다. 면적 기준입니다.` },
  { id: 'pmidx', name: 'PM 잠재 지수', good: 1, idx: 1, v: x => x.idxW ? x.idx / x.idxW / 100 : null,
    note: m => `PM 10분 안에 새로 닿는 면적 비율, 인구 밀도, 상가 밀도${m.pm_index_age ? ', 20~39세 주민 비중' : ''}을 전국 행정동 순위(0~1)로 바꿔 기하평균한 값(0~100)입니다. 기하평균이라 한 요소라도 낮으면 지수가 낮아지고, PM 10분권 면적이 ${Math.round((m.pm_index_min ?? 0.1) * 100)}% 미만인 행정동(대부분 걸어서 정류장·역에 닿는 곳)은 인구·상가가 아무리 많아도 0입니다. 높을수록 PM이 메울 공백과 수요가 함께 있는 곳입니다. 시군구·시도는 인구 가중 평균이며, 상가 자료가 아직 없는 시군구는 비어 있습니다.` },
  { id: 'steep', name: '경사로 PM 곤란 면적 비율', v: x => x.pmArea ? x.steep / x.pmArea : null,
    note: m => `PM으로 10분 거리 안이지만 경사 때문에 PM 연계가 어려운 면적의 비율입니다. 가장 가까운 정류장·역까지의 평균 경사(높이 차 ÷ 주행거리)가 ${m.grade_max * 100}%를 넘거나, 그 자리 지형 경사가 ${m.slope_max * 100}%를 넘으면 '곤란'으로 봅니다(가정값). 고도 자료의 건물 높이를 걸러낸 뒤 계산했습니다. 이 면적은 'PM 10분 안에 새로 닿는 면적'에서 빠집니다.` },
  { id: 'rail', name: '철도역 도보권 밖 면적 비율', v: x => x.railArea ? 1 - x.rail / x.railArea : null,
    note: m => `도시철도·광역철도·일반철도·KTX 역에서 직선거리 ${m.rail_m}m가 넘는 면적의 비율입니다.` },
  { id: 'few', name: `(참고) 노선 2개 이하 정류장 비율`, v: x => x.known ? x.few / x.known : null,
    note: m => `정차 노선수가 확인된 정류장 가운데 노선이 ${m.good_routes - 1}개 이하인 정류장의 비율입니다(교통카드 자료 기준). 소외 지표가 아닙니다: 서울처럼 마을버스 정류장이 촘촘한 곳은 노선 1~2개 정류장이 많아도 근처에 노선 많은 정류장이 있어 높게 나옵니다. 소외 정도는 '노선 넉넉한 정류장 도보권 밖 면적 비율'로 보세요.` },
];
const M = id => METRICS.find(m => m.id === id);

let D, C, GEO, T, U, IND, LH, AGE, OPS, BIKE, ORD, PMS = { fleet: [], parking: [], parking_sources: [], parking_units: [], seoul_companies: {} }, FLEET = {}, PARKU = {}, SURV = {}, SGGPOP, meta, map, sortSgg = { k: 'v', asc: false }, sortDong = { k: 'v', asc: false }, pickSgg = null, pickKey = null, pickSet = null;
const NARROW = window.matchMedia('(max-width: 640px)').matches;  // phones: legend and layer list start folded
const st = { metric: 'either', sido: '', urban: false, hab: true, legend: !NARROW, insMore: false, tab: 'all', gu: false };
// 일반구 (고양시 덕양구처럼 자치구가 아닌 시 안의 구): 기초지자체 단위로 볼 때는 그 시가 한 단위(key 'c' + 시 코드).
// st.gu (일반구로 나눠 보기)를 켜면 구마다 따로. pickKey: 고른 단위, pickSet: 그 단위의 시군구 코드, pickSgg: 대표 코드.
let CITY = {}, CITYK = {};
function buildCity() {
  for (const r of D) {
    const m = /^(.+시)(.+구)$/.exec(r[C.sggnm]);
    if (!m) continue;
    const c = CITYK['c' + r[C.sgg].slice(0, 4) + '0'] ??= { key: 'c' + r[C.sgg].slice(0, 4) + '0', name: m[1], sido: r[C.sido], sidonm: r[C.sidonm], sggs: [] };
    if (!c.sggs.includes(r[C.sgg])) c.sggs.push(r[C.sgg]);
    CITY[r[C.sgg]] = c;
  }
}
const unitKeyOf = (g, split = st.gu) => !split && CITY[g] ? CITY[g].key : g;
const membersOf = k => CITYK[k]?.sggs ?? [k];
const keyName = (k, r) => CITYK[k] ? `${CITYK[k].sidonm} ${CITYK[k].name}` : `${r[C.sidonm]} ${r[C.sggnm]}`;
const inPick = r => !pickSet || pickSet.has(r[C.sgg]);
const pickName = () => pickKey ? keyName(pickKey, D.find(r => r[C.sgg] === pickSgg)) : '';
// several 시군구 → one figure from per-시군구 lookups (PM 기기, 주차구역 …): the distinct units they fall in. wide: a unit
// is bigger than the members (서울 전체 값 for one 구), partial: some members have no unit.
function unitsFor(map, mem) {
  const us = [...new Set(mem.map(g => map[g]).filter(Boolean))];
  if (!us.length) return null;
  const wide = us.some(u => u.sgg.some(g => !mem.includes(g)));
  const cov = new Set(us.flatMap(u => u.sgg));
  return { us, u: us[0], wide, partial: !wide && mem.some(g => !cov.has(g)) };
}
function tripsFor(mem) {
  if (mem.length === 1) return trips(mem[0]);
  const ts = mem.map(g => T[g]);
  if (ts.some(t => !t || t.sparse)) return { trip: null, transfer: null, elder: null, sparse: true };
  const day = ts.reduce((a, t) => a + t.day, 0), pop = mem.reduce((a, g) => a + (SGGPOP[g] || 0), 0);
  const tr = ts.every(t => t.transfer != null) ? ts.reduce((a, t) => a + t.transfer, 0) : null;
  const users = ts.reduce((a, t) => a + Object.values(t.users).reduce((p, q) => p + q, 0), 0), eld = ts.reduce((a, t) => a + (t.users['경로'] || 0), 0);
  return { trip: pop ? day / pop : null, transfer: tr != null && day ? tr / day : null, elder: users ? eld / users : null, sparse: false };
}
function ageFor(rows) {  // 20~39세·70세 이상 비중 of several 시군구, from their 읍면동
  let p = 0, y = 0, o = 0;
  for (const r of rows) if (r[C.y2039] != null && r[C.pop]) { p += r[C.pop]; y += r[C.pop] * r[C.y2039]; o += r[C.pop] * (r[C.o70] || 0); }
  return p ? { y2039: y / p, o70: o / p } : null;
}
// tabs (the page's hash): 종합 shows everything; 공백·PM 연계·공급 the gap, PM and supply parts; 제도·규제 the rules.
// ins: insight groups shown (null = all); cols: 시군구 table columns (null = all); elements with data-tabs show only on those tabs
const TABS = {
  all: { name: '종합', ins: null, cols: null },
  pm: { name: '공백·PM 연계·공급', ins: ['gap', 'pm', 'supply'],
    cols: ['v', 'pop', 'area', 'stops', 'either', 'good', 'pm', 'pmidx', 'fleet', 'fleetpc', 'bikes', 'pmuse', 'park', 'parkd', 'park20', 'park30', 'pmops', 'bike', 'stores', 'firms', 'lh', 'y2039', 'o70', 'trip', 'transfer', 'elder'] },
  policy: { name: '제도·규제', ins: ['policy'], cols: ['pop', 'pmord', 'move', 'tow', 'grace', 'btow', 'dpark', 'nokick', 'pmops', 'bike', 'uarea', 'upop'] },
};
const K = k => C[(st.hab ? 'h_' : '') + k];  // the column of an area share on the current basis
const basis = () => st.hab ? '생활권 면적(산림·수면 제외)' : '전체 면적';

function agg(rows) {
  const x = { area: 0, hab: 0, pop: 0, stops: 0, known: 0, few: 0, bus: 0, rail: 0, railArea: 0, either: 0, busArea: 0, good: 0, goodArea: 0, n: rows.length,
    walk: 0, pm5: 0, pm10: 0, steep: 0, far: 0, pmArea: 0, stores: 0, storeArea: 0, idx: 0, idxW: 0 };
  const kb = K('bus500'), kr = K('rail500'), ke = K('either'), kg = K('good500'), kw = K('walk'), k5 = K('pm5'), k10 = K('pm10'), ks = K('steep'), kf = K('far');
  for (const r of rows) {
    const a = st.hab ? r[C.area_km2] * r[C.hab] : r[C.area_km2];  // weight of the area shares
    x.area += r[C.area_km2]; x.hab += r[C.area_km2] * r[C.hab]; x.pop += r[C.pop] || 0; x.stops += r[C.stops]; x.known += r[C.stops_known]; x.few += r[C.stops_few];
    if (r[kr] != null) { x.rail += a * r[kr]; x.railArea += a; }
    if (r[kb] != null) { x.bus += a * r[kb]; x.either += a * r[ke]; x.busArea += a; }
    if (r[kg] != null) { x.good += a * r[kg]; x.goodArea += a; }
    if (r[kw] != null) { x.walk += a * r[kw]; x.pm5 += a * r[k5]; x.pm10 += a * r[k10]; x.steep += a * r[ks]; x.far += a * r[kf]; x.pmArea += a; }
    if (r[C.stores] != null) { x.stores += r[C.stores]; x.storeArea += a; }
    if (r[C.pm_index] != null) { const w = Math.max(r[C.pop] || 0, 1); x.idx += w * r[C.pm_index]; x.idxW += w; }
  }
  return x;
}
const metric = () => METRICS.find(m => m.id === st.metric);
const mfmt = (m, v) => v == null ? '-' : m.idx ? (v * 100).toFixed(1) : pct(v);
const visible = r => (!st.urban || r[C.type] === '동') && (!st.sido || r[C.sido] === st.sido);
const cls = v => v == null ? -1 : Math.min(4, Math.floor(v * 5));

async function main() {
  const [stats, geo, pms] = await Promise.all([fetch(dv('data/stats.json')).then(r => r.json()), fetch(dv('data/dongs.geojson')).then(r => r.json()),
    fetch(dv('data/pm.json')).then(r => r.ok ? r.json() : null).catch(() => null)]);
  if (pms) PMS = pms;
  // each 시군구 shows the newest figures covering it (build.py picks them); a unit can cover several 시군구 (a 시 with 구, a 시도)
  for (const [g, i] of Object.entries(PMS.fleet_by_sgg || {})) FLEET[g] = PMS.fleet[i];
  for (const u of PMS.survey || []) for (const g of u.sgg) (SURV[g] ??= []).push(u);
  for (const l of Object.values(SURV)) l.sort((a, b) => a.sgg.length - b.sgg.length);  // the most specific first
  for (const u of PMS.parking_units || []) for (const g of u.sgg) PARKU[g] = u;  // parking zones per 지역 unit, as for devices
  D = stats.rows; meta = stats.meta; T = stats.sgg_trips || {}; U = stats.sgg_urban || {}; IND = stats.sgg_industrial || {}; LH = stats.sgg_lh || {}; AGE = stats.sgg_age || {}; OPS = stats.sgg_pm_ops || {}; BIKE = stats.sgg_bike_ops || {}; ORD = stats.sgg_ordinance || {}; C = Object.fromEntries(stats.cols.map((c, i) => [c, i]));
  SGGPOP = {};
  for (const r of D) SGGPOP[r[C.sgg]] = (SGGPOP[r[C.sgg]] || 0) + (r[C.pop] || 0);
  buildCity();
  $('asof').textContent = `기준: 정류장 위치 ${meta.stops_collected} 수집 · 정차 노선수 ${meta.route_days.length ? meta.route_days.map(d => d.slice(0, 4) + '-' + d.slice(4, 6) + '-' + d.slice(6)).join(', ') + ' 운행일' : '수집 중'}${meta.upis_year ? ' · 도시계획현황 ' + meta.upis_year + '년' : ''}${meta.trips_months.length ? ' · 교통카드 통행 ' + meta.trips_months.map(m => m.slice(0, 4) + '년 ' + +m.slice(4) + '월').join(', ') : ''} · 인구 ${meta.pop_ym.slice(0, 4)}년 ${+meta.pop_ym.slice(4)}월 · 행정동 경계 ${meta.boundary.replace('ver', '')}`;
  for (const m of METRICS) $('metric').add(new Option(m.name, m.id));
  const sidos = [...new Map(D.map(r => [r[C.sido], r[C.sidonm]])).entries()].sort((a, b) => a[0].localeCompare(b[0]));
  for (const [c, n] of sidos) $('sido').add(new Option(n, c));
  $('metric').onchange = e => { st.metric = e.target.value; render(); };
  $('sido').onchange = e => { st.sido = e.target.value; pickSgg = pickKey = pickSet = null; fillSgg(); render(); zoomTo(D.filter(r => !st.sido || r[C.sido] === st.sido)); };
  $('sgg').onchange = e => pickSggRow(e.target.value || null);
  $('dong').onchange = e => {
    const i = +e.target.value;
    if (e.target.value === '' || !map) return;
    zoomTo([D[i]]);
    const c = GEO.features[i].geometry, ring = c.type === 'Polygon' ? c.coordinates[0] : c.coordinates[0][0];
    const ll = ring.reduce((p, q) => [p[0] + q[0] / ring.length, p[1] + q[1] / ring.length], [0, 0]);
    new maplibregl.Popup({ maxWidth: '340px', className: 'dong-pop' }).setLngLat(ll).setHTML(dongPopup(D[i])).addTo(map);
  };
  fillSgg();
  $('urban').onchange = e => { st.urban = e.target.checked; render(); };
  $('gu').onchange = e => { st.gu = e.target.checked; render(); };
  window.addEventListener('hashchange', () => { applyTab(); render(); });
  applyTab();
  $('layers').open = !NARROW;
  const showLegend = on => { st.legend = on; $('legend').hidden = !on; $('legend-btn').hidden = on; };
  $('legend-btn').onclick = () => showLegend(true);
  $('legend').onclick = e => { if (e.target.closest('.legend-x')) showLegend(false); };
  showLegend(st.legend);
  $('ins-more').onclick = () => { st.insMore = !st.insMore; renderInsights(); };
  $('focus-lens').onchange = renderInsights;
  Beam.ready.then(() => D && renderInsights());
  if (!meta.landcover) { st.hab = false; $('hab').checked = false; $('hab').disabled = true; }
  $('hab').onchange = e => { st.hab = e.target.checked; render(); };
  GEO = geo;
  initMap(geo);
  render();
}

function initMap(geo) {
  if (typeof maplibregl === 'undefined') { $('map').innerHTML = '<p class="note" style="padding:16px">지도 라이브러리를 불러오지 못했습니다. 새로고침해 주세요.</p>'; return; }
  map = new maplibregl.Map({ container: 'map', style: 'https://tiles.openfreemap.org/styles/positron', center: [127.8, 36.2], zoom: 6, attributionControl: { compact: true } });
  map.addControl(new maplibregl.NavigationControl({ visualizePitch: true }), 'top-right');
  map.on('load', async () => {
    map.addSource('dongs', { type: 'geojson', data: geo });
    const before = map.getStyle().layers.find(l => l.type === 'symbol')?.id;
    map.addLayer({ id: 'dong-fill', type: 'fill', source: 'dongs', paint: {
      'fill-color': ['match', ['coalesce', ['feature-state', 'c'], -1], 0, RAMP[0], 1, RAMP[1], 2, RAMP[2], 3, RAMP[3], 4, RAMP[4], NODATA],
      'fill-opacity': ['case', ['boolean', ['feature-state', 'hide'], false], 0.08, 0.72] } }, before);
    map.addLayer({ id: 'dong-line', type: 'line', source: 'dongs', minzoom: 8, paint: { 'line-color': '#ffffff', 'line-width': 0.5, 'line-opacity': 0.7 } }, before);
    // terrain: shaded relief over the metric colours (so slopes show through them), and an optional 3D view.
    // MapLibre wants separate DEM sources for hillshade and 3D terrain.
    map.addSource('dem-shade', DEM);
    map.addSource('dem-3d', { ...DEM, attribution: undefined });
    map.addLayer({ id: 'hillshade', type: 'hillshade', source: 'dem-shade', layout: { visibility: 'none' }, paint: {
      'hillshade-exaggeration': ['interpolate', ['linear'], ['zoom'], 6, 0.55, 12, 0.35], 'hillshade-shadow-color': '#2e2d2a',
      'hillshade-highlight-color': '#ffffff', 'hillshade-accent-color': '#2e2d2a', 'hillshade-illumination-anchor': 'map' } }, 'dong-line');
    // the DEM has sea-floor relief too: a copy of the basemap's water fill over the shading keeps the sea flat
    const water = map.getStyle().layers.find(l => l.type === 'fill' && (l['source-layer'] === 'water' || l.id === 'water'));
    if (water) map.addLayer({ id: 'water-over-shade', type: 'fill', source: water.source, layout: { visibility: 'none' }, paint: water.paint,
      ...(water['source-layer'] ? { 'source-layer': water['source-layer'] } : {}), ...(water.filter ? { filter: water.filter } : {}) }, 'dong-line');
    $('show-terrain').onchange = () => {
      const v = $('show-terrain').checked ? 'visible' : 'none';
      for (const l of ['hillshade', 'water-over-shade']) if (map.getLayer(l)) map.setLayoutProperty(l, 'visibility', v);
      legend(metric());
    };
    $('show-terrain').onchange();
    // 시군구 without shared PM (국토교통부 첨단모빌리티 현황조사, end of 2024): diagonal hatching over their 행정동
    const cv = Object.assign(document.createElement('canvas'), { width: 8, height: 8 }), cx = cv.getContext('2d');
    cx.strokeStyle = 'rgba(46,45,42,.7)'; cx.lineWidth = 1.2;
    cx.beginPath(); cx.moveTo(0, 8); cx.lineTo(8, 0); cx.moveTo(-2, 2); cx.lineTo(2, -2); cx.moveTo(6, 10); cx.lineTo(10, 6); cx.stroke();
    map.addImage('hatch', cx.getImageData(0, 0, 8, 8), { pixelRatio: 1 });
    const noOps = D.map((r, i) => OPS[r[C.sgg]] === 0 ? i : -1).filter(i => i >= 0);
    map.addLayer({ id: 'noops', type: 'fill', source: 'dongs', filter: ['in', ['id'], ['literal', noOps]], layout: { visibility: 'none' },
      paint: { 'fill-pattern': 'hatch', 'fill-opacity': 0.9 } }, 'dong-line');
    $('show-noops').disabled = !noOps.length;
    $('show-noops').onchange = () => { map.setLayoutProperty('noops', 'visibility', $('show-noops').checked ? 'visible' : 'none'); legend(metric()); };
    $('show-noops').onchange();
    // 시군구 without shared bicycles: hatching the other way, in magenta
    const cv2 = Object.assign(document.createElement('canvas'), { width: 8, height: 8 }), cx2 = cv2.getContext('2d');
    cx2.strokeStyle = 'rgba(184,50,122,.9)'; cx2.lineWidth = 1.2;
    cx2.beginPath(); cx2.moveTo(0, 0); cx2.lineTo(8, 8); cx2.moveTo(6, -2); cx2.lineTo(10, 2); cx2.moveTo(-2, 6); cx2.lineTo(2, 10); cx2.stroke();
    map.addImage('hatch2', cx2.getImageData(0, 0, 8, 8), { pixelRatio: 1 });
    const noBike = D.map((r, i) => BIKE[r[C.sgg]]?.[0] === 0 ? i : -1).filter(i => i >= 0);
    map.addLayer({ id: 'nobike', type: 'fill', source: 'dongs', filter: ['in', ['id'], ['literal', noBike]], layout: { visibility: 'none' },
      paint: { 'fill-pattern': 'hatch2', 'fill-opacity': 0.9 } }, 'dong-line');
    $('show-nobike').disabled = !noBike.length;
    $('show-nobike').onchange = () => { map.setLayoutProperty('nobike', 'visibility', $('show-nobike').checked ? 'visible' : 'none'); legend(metric()); };
    $('show-nobike').onchange();
    // 조례·견인: the 시군구 meeting every ticked condition, coloured by PM 견인료 when 'PM 견인' is ticked
    map.addLayer({ id: 'ord', type: 'fill', source: 'dongs', paint: {
      'fill-color': ['match', ['coalesce', ['feature-state', 'ord'], -1], 0, ORDC[0], 1, ORDC[1], 2, ORDC[2], 3, ORDC[3], 4, ORDC[4], 'rgba(0,0,0,0)'],
      'fill-opacity': ['case', ['>=', ['coalesce', ['feature-state', 'ord'], -1], 0], 0.75, 0] } }, 'dong-line');
    // 광역·기초 구분: white hatching over the 시군구 that meet the conditions only through a 광역 조례
    const cv3 = Object.assign(document.createElement('canvas'), { width: 6, height: 6 }), cx3 = cv3.getContext('2d');
    cx3.strokeStyle = 'rgba(255,255,255,.95)'; cx3.lineWidth = 1.6;
    cx3.beginPath(); cx3.moveTo(0, 6); cx3.lineTo(6, 0); cx3.moveTo(-1, 1); cx3.lineTo(1, -1); cx3.moveTo(5, 7); cx3.lineTo(7, 5); cx3.stroke();
    map.addImage('hatchw', cx3.getImageData(0, 0, 6, 6), { pixelRatio: 1 });
    map.addLayer({ id: 'ord-wide', type: 'fill', source: 'dongs', paint: { 'fill-pattern': 'hatchw',
      'fill-opacity': ['case', ['boolean', ['feature-state', 'ow'], false], 1, 0] } }, 'dong-line');
    const font = map.getStyle().layers.find(l => l.type === 'symbol' && l.layout?.['text-font'])?.layout['text-font'];
    if (map.getStyle().glyphs && font) {  // 견인료 labels at the 시군구 centres (the basemap's font, which has Hangul)
      map.addSource('fees', { type: 'geojson', data: { type: 'FeatureCollection', features: feePoints() } });
      map.addLayer({ id: 'fees', type: 'symbol', source: 'fees', minzoom: 6.5, filter: ['in', ['get', 'key'], ['literal', []]],
        layout: { 'text-field': ['get', 'label'], 'text-font': font, 'text-size': ['interpolate', ['linear'], ['zoom'], 6.5, 10, 11, 14] },
        paint: { 'text-color': '#2b1d57', 'text-halo-color': '#ffffff', 'text-halo-width': 1.6 } });
    }
    for (const id of ORDK) $('ord-' + id).onchange = paintOrd;
    $('ord-lv').onchange = paintOrd;
    paintOrd();
    // PM 현황: devices per 1,000 residents of each unit, and the parking zones
    map.addLayer({ id: 'fleet', type: 'fill', source: 'dongs', layout: { visibility: 'none' }, paint: {
      'fill-color': ['match', ['coalesce', ['feature-state', 'fl'], -1], 0, FLC[0], 1, FLC[1], 2, FLC[2], 3, FLC[3], 4, FLC[4], 'rgba(0,0,0,0)'],
      'fill-opacity': ['case', ['>=', ['coalesce', ['feature-state', 'fl'], -1], 0], 0.8, 0] } }, 'dong-line');
    D.forEach((r, i) => { const u = FLEET[r[C.sgg]]; map.setFeatureState({ source: 'dongs', id: i }, { fl: u && u.pop ? FLB.findIndex(b => u.total / u.pop * 1000 < b) : -1 }); });
    map.addSource('pmpark', { type: 'geojson', data: { type: 'FeatureCollection', features: PMS.parking.map((p, i) => ({ type: 'Feature', properties: { i }, geometry: { type: 'Point', coordinates: [p[0], p[1]] } })) } });
    map.addLayer({ id: 'pmpark', type: 'circle', source: 'pmpark', layout: { visibility: 'none' }, paint: {
      'circle-radius': ['interpolate', ['linear'], ['zoom'], 6, 2.2, 10, 3.5, 15, 6], 'circle-color': '#1f6f5c',
      'circle-stroke-color': '#ffffff', 'circle-stroke-width': ['interpolate', ['linear'], ['zoom'], 8, 0, 12, 1] } });
    map.on('click', 'pmpark', e => {
      const p = PMS.parking[e.features[0].properties.i], s = PMS.parking_sources[p[5]];
      new maplibregl.Popup({ maxWidth: '260px' }).setLngLat(e.lngLat).setHTML(`<b>PM 주차구역</b><br>${esc(p[2])}${p[3] ? ' · ' + esc(p[3]) : ''}${p[4] ? '<br>주차 ' + esc(p[4]) + (/대/.test(p[4]) ? '' : '대') : ''}<br><small>${esc(s[0])} (${esc(s[1])})</small>`).addTo(map);
    });
    for (const [id, layer] of [['show-fleet', 'fleet'], ['show-park', 'pmpark']]) {
      $(id).disabled = layer === 'fleet' ? !PMS.fleet.length : !PMS.parking.length;
      $(id).onchange = () => { map.setLayoutProperty(layer, 'visibility', $(id).checked ? 'visible' : 'none'); fadeMetric(); legend(metric()); };
    }
    $('show-3d').onchange = () => {
      const on = $('show-3d').checked;
      map.setTerrain(on ? { source: 'dem-3d', exaggeration: 1.6 } : null);
      map.easeTo({ pitch: on ? 60 : 0, bearing: on ? map.getBearing() : 0, duration: 800 });
      legend(metric());
    };
    paintMap();
    map.on('click', 'dong-fill', e => {
      const r = D[e.features[0].id];
      if (!map.queryRenderedFeatures(e.point, { layers: ['stops', 'rail', 'pmpark'].filter(l => map.getLayer(l)) }).length)
        new maplibregl.Popup({ maxWidth: '340px', className: 'dong-pop' }).setLngLat(e.lngLat).setHTML(dongPopup(r)).addTo(map);
    });
    map.on('mouseenter', 'dong-fill', () => { map.getCanvas().style.cursor = 'pointer'; });
    map.on('mouseleave', 'dong-fill', () => { map.getCanvas().style.cursor = ''; });
    const [stops, rail] = await Promise.all([fetch(dv('data/stops.json')).then(r => r.json()), fetch(dv('data/stations.json')).then(r => r.json())]);
    map.addSource('stops', { type: 'geojson', data: { type: 'FeatureCollection', features: stops.map(s => ({ type: 'Feature', properties: { r: s[2], o: s[3] }, geometry: { type: 'Point', coordinates: [s[0], s[1]] } })) } });
    map.addLayer({ id: 'stops', type: 'circle', source: 'stops', minzoom: 10, paint: {
      'circle-radius': ['interpolate', ['linear'], ['zoom'], 10, 2, 15, 5],
      'circle-color': ['case', ['<', ['get', 'r'], 0], '#a3a29c', ['<', ['get', 'r'], meta.good_routes], '#eb6834', '#52514e'],
      'circle-stroke-color': '#ffffff', 'circle-stroke-width': ['interpolate', ['linear'], ['zoom'], 10, 0, 14, 1] } });
    map.addSource('rail', { type: 'geojson', data: { type: 'FeatureCollection', features: rail.map(s => ({ type: 'Feature', properties: { n: s[2] }, geometry: { type: 'Point', coordinates: [s[0], s[1]] } })) } });
    map.addLayer({ id: 'rail', type: 'circle', source: 'rail', minzoom: 7, paint: {
      'circle-radius': ['interpolate', ['linear'], ['zoom'], 7, 1.6, 11, 2.6, 15, 4.5], 'circle-color': '#6250d6', 'circle-stroke-color': '#ffffff', 'circle-stroke-width': ['interpolate', ['linear'], ['zoom'], 7, 0.5, 13, 1] } });
    map.on('click', 'stops', e => {
      const p = e.features[0].properties;
      new maplibregl.Popup({ maxWidth: '240px' }).setLngLat(e.lngLat).setHTML(`<b>버스 정류장</b><br>정차 노선 ${p.r < 0 ? '자료 없음' : p.r + '개'}${p.o ? '<br><small>위치: OpenStreetMap (국토부 파일에 없는 지역)</small>' : ''}`).addTo(map);
    });
    map.on('click', 'rail', e => new maplibregl.Popup({ maxWidth: '240px' }).setLngLat(e.lngLat).setHTML(`<b>${esc(e.features[0].properties.n)}</b><br>철도역`).addTo(map));
    map.addSource('pmgrid', { type: 'image', url: dv('data/pmgrid.png'), coordinates: [meta.grid_bounds[0], [meta.grid_bounds[1][0], meta.grid_bounds[0][1]], meta.grid_bounds[1], [meta.grid_bounds[0][0], meta.grid_bounds[1][1]]] });
    map.addLayer({ id: 'pmgrid', type: 'raster', source: 'pmgrid', paint: { 'raster-opacity': 0.85, 'raster-resampling': 'nearest' } }, 'stops');
    for (const [id, layer] of [['show-stops', 'stops'], ['show-rail', 'rail'], ['show-grid', 'pmgrid']]) {
      const set = () => { map.setLayoutProperty(layer, 'visibility', $(id).checked ? 'visible' : 'none'); if (id === 'show-grid') legend(metric()); };
      $(id).onchange = set; set();
    }
    syncLayers();  // the layers of checkboxes this tab hides stay off
    Beam.add(map, () => legend(metric()));
    Young.init(map, D, C, () => legend(metric()));
  });
}

// 조례·견인 (지자체 PM·견인 조례 분석; 광역 first, see build.py): o PM 조례, m 이동·견인 근거, t PM 견인, b 자전거 견인
const ORDK = ['o', 'm', 't', 'b', 'p', 'n'];  // + p 지정주차제, n 킥보드 없는 거리 (운영 정책)
const ORDN = { o: 'PM 조례', m: '조례에 이동·견인 근거', t: 'PM 견인', b: '자전거 견인', p: '지정주차제', n: '킥보드 없는 거리' };
const ORDC = ['#8c7fb0', '#e4d7f5', '#c3a8ea', '#9470d6', '#4f3596'];  // one colour; 견인료 ≤1.5만, ≤2만, ≤3만, more
const FEEB = [[15000, '1.5만원 이하'], [20000, '2만원'], [30000, '3만원'], [Infinity, '4만원 이상']];
const won = v => v == null ? '' : (v / 10000).toLocaleString('ko-KR', { maximumFractionDigits: 1 }) + '만원';
const ordOn = () => ORDK.filter(k => $('ord-' + k).checked);
// 조례 단위 (#ord-lv): 'split' 광역 포함 + 광역 조례만으로 해당하는 곳은 빗금, 'own' 기초 자체 조례만, 'all' 광역 포함 구분 없이.
// lv[k]: 2 기초 자체, 1 광역 조례만, 0 없음 (PM 견인은 실제 운영 현황 표가 있으면 그 표의 단위)
const ordLv = () => $('ord-lv')?.value || 'split';
const lvOf = (o, k) => o.lv ? o.lv[k] ?? 0 : o[k] ? 2 : 0;
const ordHit = sgg => { const o = ORD[sgg], on = ordOn(), min = ordLv() === 'own' ? 2 : 1; return !!(o && on.length && on.every(k => lvOf(o, k) >= min)); };
const ordWide = sgg => ordLv() === 'split' && ordHit(sgg) && ordOn().some(k => lvOf(ORD[sgg], k) === 1);
const lvText = (o, k) => !o ? '-' : (k === 'p' || k === 'n' ? ['없음', '광역(시) 시행', '시행'] : ['없음', '광역 조례만', '있음 (기초)'])[lvOf(o, k) ?? 0];
const ordClass = sgg => !ordHit(sgg) ? -1 : $('ord-t').checked && ORD[sgg].fee ? 1 + FEEB.findIndex(([v]) => ORD[sgg].fee <= v) : 0;
function feePoints() {
  const by = {};
  GEO.features.forEach((f, i) => {
    const r = D[i], o = ORD[r[C.sgg]];
    if (!o?.t || !o.fee) return;
    let x = 0, y = 0, n = 0;
    const walk = c => typeof c[0] === 'number' ? (x += c[0], y += c[1], n++) : c.forEach(walk);
    walk(f.geometry.coordinates);
    // a 시 with 구 (고양시덕양구·일산동구·일산서구) gets one label for the whole 시, so its 구 labels do not crowd each other out
    const city = /^(.+시).+구$/.exec(r[C.sggnm])?.[1], key = (city ? r[C.sido] + city : r[C.sgg]) + '|' + o.fee + '|' + (o.grace || '');
    const b = by[key] ??= { x: 0, y: 0, w: 0, fee: o.fee, planned: o.planned, grace: o.grace, sggs: new Set() };
    b.sggs.add(r[C.sgg]);
    b.x += x / n * r[C.area_km2]; b.y += y / n * r[C.area_km2]; b.w += r[C.area_km2];
  });
  FEEG = Object.fromEntries(Object.entries(by).map(([k, b]) => [k, [...b.sggs]]));
  return Object.entries(by).map(([key, b]) => ({ type: 'Feature', properties: { key, label: won(b.fee) + (b.planned ? '(예정)' : '') + (b.grace ? '\n' + graceShort(b.grace) : '') }, geometry: { type: 'Point', coordinates: [b.x / b.w, b.y / b.w] } }));
}
let FEEG = {};  // fee label key → its 시군구
// the metric colours fade while an overlay that colours 시군구 (조례·견인, PM 기기 수) is on, so its colours read cleanly
// show the tab's controls and sections; 제도·규제 starts with the 견인료 map when no 조례 condition is ticked
let autoOrd = false;
function applyTab() {
  const h = location.hash.replace('#', '');
  st.tab = TABS[h] ? h : 'all';
  document.querySelectorAll('.tabs a[data-tab]').forEach(a => { const on = a.dataset.tab === st.tab; a.classList.toggle('on', on); a.toggleAttribute('aria-current', on); });
  document.querySelectorAll('[data-tabs]').forEach(el => { el.hidden = !el.dataset.tabs.split(' ').includes(st.tab); });
  document.title = `${TABS[st.tab].name} · PM 대동여지도`;
  if (st.tab === 'policy' && !ordOn().length) { $('ord-t').checked = true; autoOrd = true; }
  else if (st.tab !== 'policy' && autoOrd) { $('ord-t').checked = false; autoOrd = false; }
  if (st.tab === 'policy') $('layers').open = true;
  syncLayers();
  paintOrd();
}
// a layer shows when its checkbox is ticked and the checkbox is on this tab
const LAYERS = [['show-stops', 'stops'], ['show-rail', 'rail'], ['show-grid', 'pmgrid'], ['show-fleet', 'fleet'], ['show-park', 'pmpark'],
  ['show-noops', 'noops'], ['show-nobike', 'nobike'], ['show-terrain', 'hillshade'], ['show-terrain', 'water-over-shade']];
function syncLayers() {
  if (!map) return;
  for (const [id, layer] of LAYERS) if (map.getLayer(layer)) map.setLayoutProperty(layer, 'visibility', $(id).checked && !$(id).closest('[data-tabs]')?.hidden ? 'visible' : 'none');
}
function fadeMetric() {
  if (map?.getLayer('dong-fill')) map.setPaintProperty('dong-fill', 'fill-opacity', ['case', ['boolean', ['feature-state', 'hide'], false], 0.08,
    st.tab === 'policy' ? 0 : ordOn().length || $('show-fleet').checked ? 0.22 : 0.72]);
}
function paintOrd() {
  if (!map || !map.getLayer('ord')) return;
  D.forEach((r, i) => map.setFeatureState({ source: 'dongs', id: i }, { ord: ordClass(r[C.sgg]), ow: ordWide(r[C.sgg]) }));
  fadeMetric();
  if (map.getLayer('fees')) map.setFilter('fees', ['in', ['get', 'key'], ['literal', $('ord-t').checked ? Object.keys(FEEG).filter(k => FEEG[k].some(ordHit)) : []]]);
  legend(metric());
  renderInsights();
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
    line('주민등록인구', fmt(r[C.pop])) + line('면적 (생활권)', r[C.area_km2].toFixed(2) + '㎢ (' + pct(r[C.hab]) + ')') + line('버스 정류장', fmt(r[C.stops]) + '곳') +
    METRICS.map(m => line(m.name, mfmt(m, m.v(x)))).join('') + (OPS[r[C.sgg]] != null ? line(`공유 PM / 자전거 (${opsDate()})`, opsText(OPS[r[C.sgg]]) + ' / ' + bikeText(BIKE[r[C.sgg]])) : '') + (FLEET[r[C.sgg]] ? line('PM 기기', fleetText(FLEET[r[C.sgg]], r[C.sgg])) : '') + (() => { const sv = survey(r[C.sgg]); return (bikeLine(sv) ? line(`공유자전거 (${meta2()})`, bikeLine(sv)) : '') + (useLine(sv) ? line(`앱 기반 이용 횟수 (${meta2()})`, useLine(sv)) : ''); })() + (PARKU[r[C.sgg]] ? line(`PM 주차구역 (${esc(PARKU[r[C.sgg]].name)})`, fmt(PARKU[r[C.sgg]].n) + '곳' + (() => { const g = unitGap(PARKU[r[C.sgg]]); return g ? ` · 1㎢당 ${g.d.toFixed(1)}곳` : ''; })()) : '') + (ORD[r[C.sgg]] ? line('PM 조례', lvText(ORD[r[C.sgg]], 'o')) + line('조례에 이동·견인 근거', lvText(ORD[r[C.sgg]], 'm')) + line('PM 견인', towText(ORD[r[C.sgg]])) + (ORD[r[C.sgg]].t ? line('유예시간', graceText(ORD[r[C.sgg]])) : '') + line('자전거 견인', bikeTow(ORD[r[C.sgg]])) + line('지정주차제', lvText(ORD[r[C.sgg]], 'p')) + line('킥보드 없는 거리', lvText(ORD[r[C.sgg]], 'n')) : '') + (Beam.kind(r[C.sgg]) ? line('빔모빌리티 운영', Beam.kind(r[C.sgg])) : '') + (r[C.stores] != null ? line('상가업소', fmt(r[C.stores]) + '곳') : '') + (r[C.y2039] != null ? line('20~39세 / 70세 이상', pct(r[C.y2039]) + ' / ' + pct(r[C.o70])) + line('20~39세 인구수 · 비중 순위', (() => { const i = D.indexOf(r); return Young.rankText(i, 'n') + ' · ' + Young.rankText(i, 's'); })()) : '') + (U[r[C.sgg]] ? line(`법정 도시지역 면적 (${U[r[C.sgg]].city ? esc(U[r[C.sgg]].city) + ' 전체' : '시군구'})`, pct(U[r[C.sgg]].area)) : '') + (() => { const t = trips(r[C.sgg]); return t.sparse ? line('교통카드 승차 (시군구)', '자료 부족') : t.trip == null ? '' :
      line('주민 1인당 하루 승차 (시군구)', t.trip.toFixed(2)) + line('환승 통행 비중 (시군구)', pct(t.transfer)); })() + '</table>' +
    (r[C.stop_gap] ? '<small>이 시군구는 국토부 파일과 OpenStreetMap 모두 정류장이 크게 부족해 버스 지표를 비워 두었습니다.</small><br>' : '') +
    (r[C.osm_fill] ? '<small>이 시군구는 국토부 정류장 파일에 거의 없어 OpenStreetMap 정류장으로 보완했습니다.</small><br>' : '') +
    (r[C.route_ok] ? '' : '<small>이 시군구는 정차 노선수 자료가 없거나 정류장 연결이 부족합니다.</small>');
}

// 시도 → 시군구 → 읍면동 drill-down
function fillSgg() {
  const sel = $('sgg');
  sel.length = 1;
  // 기초지자체 by name; a 시 with 일반구 first as a whole ('고양시 (시 전체)'), then its 구 indented
  if (st.sido) for (const [c, n] of [...new Map(D.filter(r => r[C.sido] === st.sido).map(r => [r[C.sgg], r[C.sggnm]])).entries()].sort((a, b) => a[1].localeCompare(b[1]))) {
    const city = CITY[c];
    if (city && city.sggs[0] === c) sel.add(new Option(`${city.name} (시 전체)`, city.key));
    sel.add(new Option(city ? `　└ ${n.slice(city.name.length)}` : n, c));
  }
  sel.disabled = !st.sido;
  fillDong();
}

function fillDong() {
  const sel = $('dong');
  sel.length = 1;
  if (pickSet) D.forEach((r, i) => { if (pickSet.has(r[C.sgg])) sel.add(new Option(pickSet.size > 1 ? `${r[C.sggnm].slice(CITY[r[C.sgg]]?.name.length ?? 0)} ${r[C.name]}` : r[C.name], i)); });
  sel.disabled = !pickSgg;
}

function pickSggRow(key) {
  pickKey = key || null; pickSet = key ? new Set(membersOf(key)) : null; pickSgg = key ? membersOf(key)[0] : null;
  if (key && !st.sido) { st.sido = D.find(r => r[C.sgg] === pickSgg)[C.sido]; $('sido').value = st.sido; fillSgg(); render(); }
  $('sgg').value = key || '';
  fillDong();
  renderDongs(D.filter(visible), metric());
  renderInsights();
  zoomTo(D.filter(d => key ? pickSet.has(d[C.sgg]) : !st.sido || d[C.sido] === st.sido));
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
  $('metric-note').textContent = m.note(meta) + (m.idx || m.id === 'few' ? '' : ` [${basis()} 기준]`);
  const rows = D.filter(visible);
  const x = agg(rows);
  $('summary').innerHTML = `<b>${esc(st.sido ? rows[0]?.[C.sidonm] ?? '' : '전국')}${st.urban ? ' 동 지역' : ''}</b>: 행정동 ${fmt(x.n)}곳 · 인구 ${fmt(x.pop)}명 · 면적 ${fmt(x.area)}㎢ · 버스 정류장 ${fmt(x.stops)}곳 · ${esc(m.name)} <b>${mfmt(m, m.v(x))}</b>` +
    (x.pmArea ? `<br>${basis()} 구성: 도보권 ${pct(x.walk / x.pmArea)} · PM 5분권 ${pct(x.pm5 / x.pmArea)} · PM 10분권 ${pct(x.pm10 / x.pmArea)} · 경사로 PM 곤란 ${pct(x.steep / x.pmArea)} · PM으로도 먼 곳 ${pct(x.far / x.pmArea)}` : '') +
    (x.area ? ` · 생활권 면적은 전체의 ${pct(x.hab / x.area)}` : '');
  legend(m);
  paintMap();
  renderSgg(rows, m);
  renderDongs(rows, m);
  renderInsights();
}

// plain-language findings for the current selection, in short groups: 대중교통 공백 / PM으로 메울 곳 / 공급 / 제도.
// Data caveats go to a folded '자료 참고' list.
const INS_G = [['gap', '대중교통 공백'], ['pm', 'PM으로 메울 수 있는 곳'], ['supply', 'PM·자전거 공급'], ['policy', '제도·규제']];
const shortName = n => esc(String(n).replace(/^\S+ /, ''));
const pp = v => v == null ? '-' : Math.round(v * 100) + '%';  // calm percentages: no decimals in prose
function renderInsights() {
  const pmM = M('pm'), goodM = M('good'), eM = M('either');
  const scope = D.filter(r => (!st.urban || r[C.type] === '동') && (!st.sido || r[C.sido] === st.sido) && inPick(r));
  if (!scope.length) { $('insights').innerHTML = ''; $('ins-head').innerHTML = ''; return; }
  const name = pickSgg ? pickName() : st.sido ? scope[0][C.sidonm] : '전국';
  $('ins-title').textContent = `지역별 인사이트 · ${name}${st.urban ? ' 동 지역' : ''}`;
  const x = agg(scope), T = TABS[st.tab], groups = {}, notes = [];
  renderHead(scope, x);
  renderFocus();
  const add = (g, html) => { if (!T.ins || T.ins.includes(g)) (groups[g] ??= []).push(html); };
  const nat = agg(D.filter(r => !st.urban || r[C.type] === '동'));
  const list = (rows, k, f, n = 3) => rows.filter(r => r[k] != null).sort((a, b) => b[k] - a[k]).slice(0, n).map(f).join(', ');
  const hab = st.hab ? '생활권' : '전체';
  if (!pickSgg) {
    // sggs: one code per 기초지자체 (or 일반구 when split) for counting; allSggs for unit lookups (기기·주차구역)
    const sg = sgRows(scope, pmM).filter(r => !r.gap), allSggs = [...new Set(scope.map(r => r[C.sgg]))], sggs = [...new Map(scope.map(r => [unitKeyOf(r[C.sgg]), r[C.sgg]])).values()];
    // 대중교통 공백
    const e = eM.v(x);
    if (e != null) add('gap', `${hab} 땅의 <b>${pp(e)}</b>는 버스 정류장·철도역까지 걸어서 가기 어렵습니다.`);
    const t1 = list(sg, 'either', r => `${shortName(r.name)} ${pp(r.either)}`);
    if (t1) add('gap', `그 비율이 높은 곳: <b>${t1}</b>`);
    const t2 = list(sg, 'good', r => `${shortName(r.name)} ${pp(r.good)}`);
    if (t2) add('gap', `노선이 ${meta.good_routes}개 이상인 정류장 기준으로 보면: ${t2}`);
    // PM
    if (x.pmArea) add('pm', `PM을 타면 10분 안에 정류장·역에 닿는 땅이 <b>${pp((x.pm5 + x.pm10) / x.pmArea)}</b> 더 있습니다.` + (name !== '전국' && nat.pmArea ? ` (전국 ${pp((nat.pm5 + nat.pm10) / nat.pmArea)})` : ''));
    const t3 = list(sg, 'pm', r => `${shortName(r.name)} ${pp(r.pm)}`);
    if (t3) add('pm', `PM으로 메울 땅이 넓은 곳: <b>${t3}</b>`);
    const t4 = list(sg, 'pmidx', r => shortName(r.name));
    if (t4) add('pm', `사람·상가가 많아 PM 수요도 클 곳: ${t4}`);
    // 공급
    const nOff = sggs.filter(g => OPS[g] === 0).length, off = sg.filter(r => r.pmops === 0);
    if (Object.keys(OPS).length) add('supply', nOff ? `공유 PM이 없는 시군구는 <b>${nOff}곳</b>입니다(${opsDate()}).` + (off.length ? ` 이 중 PM으로 메울 땅이 넓은 곳: ${list(off, 'pm', r => shortName(r.name))}` : '') : `모든 시군구에 공유 PM이 있습니다(${opsDate()}).`);
    const pus = [...new Set(allSggs.map(g => PARKU[g]).filter(Boolean))].map(u => ({ u, g: unitGap(u) })).filter(v => v.g);
    if (pus.length) {
      const all = parkGap(pus.reduce((a, v) => a + v.u.n, 0), pus.reduce((a, v) => a + unitArea(v.u), 0));
      add('supply', `PM 주차구역은 ${hab} 1㎢당 <b>${all.d.toFixed(1)}곳</b>입니다. 주차가 가장 잘 지켜진다는 1㎢당 20곳에 ` + (all.gaps[0].short > 0 ? `<b>${pp(all.gaps[0].short)} 모자랍니다</b>.` : '이미 닿습니다.') + ` <small>(자료가 있는 ${pus.length}개 지역)</small>`);
    }
    // 제도
    if (Object.keys(ORD).length) {
      const lvN = k => { const n = [0, 0, 0]; for (const g of sggs) if (ORD[g]) n[lvOf(ORD[g], k)]++; return n; };
      const o = lvN('o'), m = lvN('m'), t = lvN('t'), b = lvN('b');
      const tows = sggs.filter(g => ORD[g]?.t), fees = tows.map(g => ORD[g].fee).filter(Boolean).sort((p, q) => p - q);
      add('policy', `PM 조례는 시군구 ${sggs.length}곳 중 <b>${o[2]}곳</b>이 직접 두고 있고, ${o[1]}곳은 광역(시·도) 조례만 적용됩니다.`);
      if (st.tab === 'policy') add('policy', `조례에 PM을 옮기거나 견인할 근거가 있는 곳: 직접 ${m[2]}곳, 광역 조례로 ${m[1]}곳.`);
      add('policy', `PM을 견인하는 곳은 <b>${tows.length}곳</b>` + (fees.length ? `이고, 견인료는 보통 ${won(fees[Math.floor(fees.length / 2)])}(${won(fees[0])}~${won(fees[fees.length - 1])})입니다.` : '입니다.'));
      const gr = {}; for (const g of tows) if (ORD[g].grace) gr[ORD[g].grace] = (gr[ORD[g].grace] || 0) + 1;
      if (Object.keys(gr).length) add('policy', '세워 둔 뒤 견인까지 기다려 주는 시간: ' + Object.entries(gr).sort((p, q) => graceMin(p[0]) - graceMin(q[0])).map(([k, n]) => `${esc(k)} ${n}곳`).join(', ') + '.');
      if (st.tab === 'policy') add('policy', `자전거도 견인하는 곳: ${b[2] + b[1]}곳 (직접 ${b[2]}, 광역 ${b[1]}).`);
      const zp = lvN('p'), zn = lvN('n'), zl = (k, n) => { const x = sggs.filter(g => lvOf(ORD[g] || {}, k) > 0).map(g => shortName(keyName(unitKeyOf(g), D.find(r => r[C.sgg] === g)))); return n[2] + n[1] ? `<b>${n[2] + n[1]}곳</b>` + (x.length <= 12 ? ` (${x.join(', ')})` : '') : '없음'; };
      add('policy', `지정주차제(정해진 곳에만 PM 주차): ${zl('p', zp)}${zp[1] ? ` <small>광역 시행 ${zp[1]}곳 포함</small>` : ''}. 킥보드 없는 거리: ${zl('n', zn)}.`);
    }
    const units = [...new Set(allSggs.map(g => FLEET[g]).filter(Boolean))];
    if (units.length) notes.push(`PM 기기 수는 지역마다 기준일이 다릅니다(${units.map(u => u.date.split(' · ')).flat().sort()[0]} ~ ${units.map(u => u.date.split(' · ')).flat().sort().pop()}).`);
  } else {
    const g = pickSgg, sidoX = agg(D.filter(r => (!st.urban || r[C.type] === '동') && r[C.sido] === scope[0][C.sido]));
    // 대중교통 공백
    const e = eM.v(x), ne = eM.v(nat), gd = goodM.v(x);
    if (e != null) add('gap', `${hab} 땅의 <b>${pp(e)}</b>는 버스 정류장·철도역까지 걸어서 가기 어렵습니다` + (ne != null ? ` (전국 평균 ${pp(ne)}).` : '.'));
    if (gd != null && e != null && gd - e >= 0.01) add('gap', `정류장은 가까워도 노선이 1~${meta.good_routes - 1}개뿐인 땅이 ${pp(gd - e)} 더 있습니다.`);
    const P = pickRow(scope), t = P, ag = P.y2039 != null ? P : null;
    if (t.elder != null) add('gap', `버스·지하철 승차의 ${pp(t.elder)}가 어르신(경로) 승차입니다.`);
    // PM
    const v = pmM.v(x), sv = pmM.v(sidoX);
    if (v != null) add('pm', `PM을 타면 10분 안에 정류장·역에 닿는 땅이 <b>${pp(v)}</b> 더 있습니다` + (sv != null ? ` (${esc(scope[0][C.sidonm])} 평균 ${pp(sv)}).` : '.'));
    if (x.pmArea && (x.steep + x.far) / x.pmArea >= 0.01) add('pm', `경사가 급하거나 PM으로도 먼 땅은 ${pp((x.steep + x.far) / x.pmArea)}입니다.`);
    const dt = list(scope, C.pm_index, r => esc(r[C.name]));
    if (dt) add('pm', `PM이 특히 쓸모 있을 동네: <b>${dt}</b>`);
    if (ag) add('pm', `주민 가운데 20~39세는 ${pp(ag.y2039)}, 70세 이상은 ${pp(ag.o70)}입니다.`);
    if (IND[g]) add('pm', `산업단지 ${IND[g].n}곳(가동업체 ${fmt(IND[g].firms)}곳)이 있어 출퇴근 PM 연계 후보가 됩니다.`);
    // 공급
    const svy = P.sv;
    if (OPS[g] != null) add('supply', OPS[g] ? `공유 PM이 운영되고 있습니다(${opsDate()}).` : `<b>공유 PM이 없습니다</b>(${opsDate()}). PM으로 메울 땅은 서비스가 들어와야 쓸 수 있습니다.`);
    const fu = P.fleetU;
    if (fu) add('supply', (P.fl.wide ? `PM 기기는 ${esc(fu.name)} 전체로만 집계돼 있습니다: <b>${fmt(fu.total)}대</b>` : `PM 기기: <b>${fmt(P.fleet)}대</b>${P.fl.partial ? ' (일부 구만)' : ''}`) +
      (P.fl.us.length === 1 && fu.ops.length ? ` (${fu.ops.slice(0, 3).map(([o, n]) => `${esc(o)} ${fmt(n)}`).join(', ')}${fu.ops.length > 3 ? ' 등' : ''})` : '') + `. <small>${esc(P.fleetDate)}</small>`);
    if (useLine(svy)) add('supply', `앱으로 빌린 횟수(${meta2()}): ${useLine(svy)}`);
    if (BIKE[g]) add('supply', `공유자전거: ${bikeText(BIKE[g])}` + (bikeLine(svy) ? ` · ${bikeLine(svy)}` : '') + '.');
    if (P.parkd != null) add('supply', `PM 주차구역은 ${hab} 1㎢당 <b>${P.parkd.toFixed(1)}곳</b>입니다${P.pk.wide ? ` <small>(${esc(P.pk.u.name)} 전체)</small>` : P.pk.partial ? ' <small>(일부 구만)</small>' : ''}. 1㎢당 20곳에 ` + (P.park20 > 0 ? `<b>${pp(P.park20)} 모자랍니다</b>` : '이미 닿습니다') + ` (30곳 기준: ${P.park30 > 0 ? pp(P.park30) + ' 부족' : '충족'}).`);
    else if (PMS.parking_units?.length) notes.push('이 시군구는 PM 주차구역 자료가 없습니다(0곳이라는 뜻이 아님).');
    // 제도
    const o = ORD[g];
    if (o) {
      add('policy', `PM 조례: ${lvText(o, 'o')}. 옮기거나 견인할 근거: ${lvText(o, 'm')}.`);
      add('policy', o.t ? `PM 견인: <b>${towText(o)}</b>` + (o.grace ? `, ${/즉시/.test(o.grace) ? '<b>즉시 견인</b>' : `${esc(o.grace)} 기다린 뒤 견인`}` : '') + (o.note ? ` <small>(${esc(o.note)})</small>` : '') + '.' : 'PM을 견인하지 않습니다.');
      add('policy', `자전거 견인: ${bikeTow(o)}.`);
      add('policy', `지정주차제: ${lvText(o, 'p')}. 킥보드 없는 거리: ${lvText(o, 'n')}.`);
      if (o.zsrc && (o.p || o.n)) notes.push(`지정주차제·킥보드 없는 거리는 ${esc(o.zsrc)} 기준입니다.`);
      if (o.practice) notes.push(`견인 여부·견인료·유예시간은 ${esc(o.practice)} 기준입니다.`);
      if (o.wide.length) notes.push(`광역 조례도 함께 적용됩니다: ${o.wide.map(w => esc(w[0])).join(', ')}.`);
    }
    if (U[g] && st.tab === 'policy') add('policy', `법정 도시지역이 면적의 ${pp(U[g].area)}, 주민의 ${pp(U[g].pop)}입니다${U[g].city ? ` (${esc(U[g].city)} 전체)` : ''}.`);
    if (t.sparse) notes.push('교통카드 자료가 거의 들어오지 않는 시군구라 승차 관련 값은 비워 둡니다(실제 이용이 없다는 뜻이 아님).');
  }
  const gaps = [...new Set(scope.filter(r => r[C.stop_gap]).map(r => r[C.sggnm]))], noRoute = new Set(scope.filter(r => !r[C.route_ok]).map(r => r[C.sgg])).size;
  const noCard = pickSgg ? 0 : new Set(scope.filter(r => trips(r[C.sgg]).sparse).map(r => r[C.sgg])).size;
  if (gaps.length) notes.push(`정류장 위치 자료가 부족해 버스 지표를 뺀 곳: ${gaps.map(esc).join(', ')}.`);
  if (noRoute) notes.push(`정차 노선 수 자료가 없는 시군구 ${noRoute}곳은 노선 관련 값이 비어 있습니다.`);
  if (noCard) notes.push(`교통카드 자료가 거의 없는 시군구 ${noCard}곳은 승차 관련 값을 비워 둡니다.`);
  const shown = INS_G.filter(([k]) => groups[k]?.length), cut = NARROW && !st.insMore ? 1 : shown.length;
  $('insights').innerHTML = shown.slice(0, cut).map(([k, h]) => `<div class="ins-group"><h3>${h}</h3><ul>${groups[k].map(v => `<li>${v}</li>`).join('')}</ul></div>`).join('') +
    (notes.length && (!NARROW || st.insMore) ? `<details class="ins-notes"><summary>자료 참고 (${notes.length})</summary><ul>${notes.map(n => `<li>${n}</li>`).join('')}</ul></details>` : '');
  $('ins-more').hidden = !NARROW || shown.length <= 1;
  $('ins-more').textContent = st.insMore ? '접기' : `더 보기 (${shown.length - 1})`;
}

function legend(m) {
  const lab = m.idx ? ['0~20', '20~40', '40~60', '60~80', '80~100'] : ['0~20%', '20~40%', '40~60%', '60~80%', '80~100%'];
  const row = (c, t, cls = '') => `<div class="row"><i class="${cls}" style="background:${c}"></i>${t}</div>`;
  const stop = [['#eb6834', `노선 ${meta.good_routes - 1}개 이하`], ['#52514e', `${meta.good_routes}개 이상`], ['#a3a29c', '노선 수 모름']];
  const grid = [['#eb6834', 'PM 5분권'], ['#f6b38f', 'PM 10분권'], ['rgba(24,118,110,.75)', '경사로 PM 곤란'], ['rgba(82,81,78,.55)', 'PM으로도 먼 곳'], ['rgba(214,213,208,.75)', '정류장 자료 부족'], ['rgba(150,168,128,.45)', '산림·수면 (생활권 밖)']];
  const rail = '<i class="pt" style="background:#6250d6;border:1.5px solid #fff;outline:1px solid #6250d6"></i>';
  // phones: the colour scale as one bar and the stop kinds on one line, so the legend leaves the map visible
  const scale = NARROW
    ? `<div class="bar">${RAMP.map(c => `<i style="background:${c}"></i>`).join('')}</div><div class="bar-l"><span>${m.idx ? '0' : '0%'}</span><span>${m.idx ? '100' : '100%'}</span></div>` + row(NODATA, '자료 없음')
    : RAMP.map((c, i) => row(c, lab[i])).join('') + row(NODATA, '자료 없음');
  const stops = NARROW
    ? `<div class="row wrap" style="margin-top:4px">정류장 ${stop.map(([c, t]) => `<span><i class="pt" style="background:${c}"></i>${t}</span>`).join('')}<span>${rail}철도역</span></div>`
    : `<div style="margin-top:4px"></div>` + stop.map(([c, t]) => row(c, `정류장(${t})`, 'pt')).join('') + `<div class="row">${rail}철도역</div>`;
  const pol = st.tab === 'policy';
  $('legend').innerHTML = `<div class="t"><span>${pol ? '조례·규제' : esc(m.name)}</span><button class="legend-x" type="button" aria-label="범례 닫기">×</button></div>` + (pol ? '' : scale + stops) +
    ($('show-grid').checked ? '<div class="row" style="margin-top:4px"><b>PM 연계 격자</b> <small>(도보권은 투명)</small></div>' + grid.map(([c, t]) => row(c, t)).join('') : '') +
    ($('show-noops').checked ? `<div class="row" style="margin-top:4px"><i style="background:repeating-linear-gradient(135deg,#2e2d2a 0 1.5px,transparent 1.5px 5px)"></i>공유 PM 미운영 시군구 (${opsDate()})</div>` : '') +
    ($('show-nobike').checked ? `<div class="row"><i style="background:repeating-linear-gradient(45deg,#b8327a 0 1.5px,transparent 1.5px 5px)"></i>공유자전거 미운영 시군구 (${opsDate()})</div>` : '') +
    ($('show-fleet').checked ? '<div class="row" style="margin-top:4px"><b>PM 기기 수 (인구 1천 명당)</b></div>' + ['2대 미만', '2~4대', '4~8대', '8~16대', '16대 이상'].map((t, i) => row(FLC[i], t)).join('') + '<div class="row"><small>자료가 있는 지역만, 기준일 제각각</small></div>' : '') +
    ($('show-park').checked ? `<div class="row"><i class="pt" style="background:#1f6f5c"></i>PM 주차구역 (좌표 있는 ${fmt(PMS.parking.length)}곳)</div>` : '') +
    (ordOn().length ? `<div class="row" style="margin-top:4px"><b>${ordOn().map(k => ORDN[k]).join(' + ')}</b></div>` + ($('ord-t').checked
      ? FEEB.map(([, t], i) => row(ORDC[i + 1], 'PM 견인료 ' + t)).join('') + (Object.keys(ORD).some(g => ordHit(g) && !ORD[g].fee) ? row(ORDC[0], '견인료 금액 없음') : '')
      : row(ORDC[0], '해당 시군구')) + (ordLv() === 'split' ? `<div class="row"><i style="background:repeating-linear-gradient(135deg,#fff 0 1.5px,${ORDC[0]} 1.5px 4px)"></i>빗금: 광역(시·도) 조례·정책으로만 해당 (기초 자체는 없음)</div>` : '') + `<div class="row"><small>${ordLv() === 'own' ? '기초지자체 자체 조례만 셉니다. ' : '광역 조례가 있으면 소속 시군구도 해당으로 칩니다. '}${$('ord-t').checked ? '견인 여부·견인료는 실제 견인 운영 현황 표가 있으면 그것을 우선, 지도 숫자 아래는 유예시간. ' : ''}${Object.keys(ORD).filter(ordHit).length}곳</small></div>` : '') +
    ($('show-terrain').checked || $('show-3d').checked ? `<div class="row" style="margin-top:4px"><small>${$('show-terrain').checked ? '지형 음영: 짙을수록 급한 경사. ' : ''}${$('show-3d').checked ? '3D: 높이 1.6배 과장, 나침반을 누르면 정북으로.' : ''}</small></div>` : '') +
    Beam.legendRows() + Young.legendRows() +
    (st.tab === 'policy' ? '' : `<div class="row"><small>정류장은 확대(줌 10 이상)하면 보입니다.</small></div>`);
}

const opsDate = () => meta.pm_ops_date ? `${meta.pm_ops_date.slice(0, 4)}년 말` : '';
const opsText = v => v == null ? '-' : v ? '운영' : '<b>미운영</b>';
const bikeText = v => v == null ? '-' : v[0] ? '운영' + (v[1] ? `(${v[1]})` : '') : '<b>미운영</b>';
const yn = v => v == null ? '-' : v ? '있음' : '없음';
// PM 주차구역 density against the 1㎢당 20·30곳 benchmark, on the area basis of the toggle (생활권 or whole area)
const PARK_T = [20, 30];
const parkArea = x => st.hab ? x.hab : x.area;
const unitAgg = {};  // area of a parking unit (all its 시군구), per basis
const unitArea = u => (unitAgg[u.sgg.join()] ??= agg(D.filter(r => u.sgg.includes(r[C.sgg])))) && parkArea(unitAgg[u.sgg.join()]);
const unitGap = u => u ? parkGap(u.n, unitArea(u)) : null;
function parkGap(n, area) {  // {d: zones per ㎢, gaps: [{t, need, short}]}
  if (n == null || !area) return null;
  return { d: n / area, gaps: PARK_T.map(t => ({ t, need: Math.ceil(t * area), short: Math.max(0, 1 - n / (t * area)) })) };
}
const gapText = g => g.gaps.map(({ t, need, short }) => `${t}곳 기준(${fmt(need)}곳) 대비 ${short > 0 ? `<b>${pct(short)} 부족</b>` : '충족'}`).join(', ');
const meta2 = () => (PMS.survey_date || '').slice(0, 4) + '년 말';
const FLB = [2, 4, 8, 16, Infinity], FLC = ['#d7efe8', '#a3d9c9', '#62b9a2', '#2e8b74', '#155e4d'];  // devices per 1,000 residents
// one line for a unit's devices: 1,470대 (킥보드) · 지쿠 750 · 더스윙 720 · 2026-07-31
function fleetText(u, sgg) {
  if (!u) return '';
  const kinds = [u.kick && `킥보드 ${fmt(u.kick)}`, u.bike && `자전거 ${fmt(u.bike)}`, u.mixed && `구분 없음 ${fmt(u.mixed)}`].filter(Boolean);
  const ops = u.ops.length ? u.ops.map(([o, n]) => `${esc(o)} ${fmt(n)}`).join(', ') : u.n_ops ? `${u.n_ops}개 사` : '';
  const co = PMS.seoul_companies[sgg];
  return `<b>${fmt(u.total)}대</b>` + (kinds.length > 1 ? ` (${kinds.join(' · ')})` : u.kick ? ' (킥보드)' : ' (킥보드·자전거 구분 없음)') + (ops ? ` · ${ops}` : '') +
    (u.sgg.length > 1 ? ` <small>· ${esc(u.name)} 전체${u.partial ? '(일부 시군구는 더 최신 자료 사용)' : ''}</small>` : '') + (co ? ` <small>· 이 구 운영 업체 ${co}곳</small>` : '') + ` <small>· ${esc(u.date)} 기준</small>`;
}
// the survey's other figures for a 시군구 (2024년 말): each field from the most specific unit that has it
function survey(sgg) {
  const l = SURV[sgg];
  if (!l) return null;
  const get = k => l.find(u => u[k] != null);
  const pub = get('bike_pub'), pri = get('bike_pri'), pu = get('pm_use'), bu = get('bike_use');
  return { pub, pri, pu, bu, bikes: pub || pri ? (pub?.bike_pub || 0) + (pri && pri === pub ? pri.bike_pri || 0 : pri?.bike_pri || 0) : null };
}
function bikeLine(sv) {
  if (!sv || (!sv.pub && !sv.pri)) return '';
  const p = sv.pub ? `공영 ${fmt(sv.pub.bike_pub)}대${sv.pub.bike_pub_name ? '(' + esc(sv.pub.bike_pub_name) + ')' : ''}` : '';
  const q = sv.pri ? `민영 ${fmt(sv.pri.bike_pri)}대` : '';
  const u = sv.pub || sv.pri;
  return [p, q].filter(Boolean).join(' · ') + (u.sgg.length > 1 ? ` <small>· ${esc(u.name)} 전체</small>` : '');
}
function useLine(sv) {
  if (!sv || (!sv.pu && !sv.bu)) return '';
  const per = (u, k) => u.pop ? ` (1만 명당 ${(u[k] / u.pop * 1e4).toFixed(1)})` : '';
  return [sv.pu && `PM ${fmt(sv.pu.pm_use)}회${per(sv.pu, 'pm_use')}`, sv.bu && `자전거(민영) ${fmt(sv.bu.bike_use)}회${per(sv.bu, 'bike_use')}`].filter(Boolean).join(' · ') +
    ((sv.pu || sv.bu).sgg.length > 1 ? ` <small>· ${esc((sv.pu || sv.bu).name)} 전체</small>` : '');
}
// 유예시간: how long a PM may stand where it should not before it is towed (실제 견인 운영 현황 표; 조례에는 없음)
const graceMin = g => !g ? null : /즉시/.test(g) ? 0 : /(\d+)\s*분/.test(g) ? +g.match(/(\d+)\s*분/)[1] : /(\d+)\s*시간/.test(g) ? 60 * g.match(/(\d+)\s*시간/)[1] : null;
const graceShort = g => /즉시/.test(g) ? '즉시' : '유예 ' + g;
const graceText = o => !o?.t ? '-' : (o.grace ? esc(o.grace) : '자료 없음') + (o.note ? ` <small>(${esc(o.note)})</small>` : '');
// 자전거 견인료는 보통 PM 견인료와 같아 같은 금액으로 표시
const bikeTow = o => !o ? '-' : !o.b ? '없음' : (o.t && o.fee ? won(o.fee) + ' <small>(PM과 같은 금액으로 봄)</small>' : '있음') + (lvOf(o, 'b') === 1 ? ' <small>광역 조례</small>' : '');
const towText = o => !o ? '-' : !o.t ? '없음' : (o.fee ? won(o.fee) + (o.planned ? '(예정)' : '') : '견인') + (o.src && o.wide.some(w => w[0] === o.src) ? ` <small title="${esc(o.src)} 조례 기준">광역</small>` : '');

const isWide = u => !!u && u.sgg.length > 1;
const unitShort = u => String(u.name).split(' ').pop().replace(/(특별시|광역시|특별자치시|특별자치도)$/, '');
const wideTxt = (u, txt) => `<small class="wide" title="시군구별 자료가 없어 ${esc(u.name)} 전체 값만 있습니다">${esc(unitShort(u))} 전체 ${txt}</small>`;
const partTag = x => x?.partial ? ' <small class="wide" title="일부 구만 자료가 있습니다">일부 구만</small>' : '';
const avgTag = u => isWide(u) ? ` <small class="wide" title="${esc(u.name)} 전체 값">${esc(unitShort(u))} 평균</small>` : '';
// one row per 시군구 (기초지자체; 일반구는 st.gu일 때만 따로). keyOf can force one row (the picked unit).
const pickRow = scope => sgRows(scope, metric(), () => pickKey)[0];
function sgRows(rows, m, keyOf = r => unitKeyOf(r[C.sgg])) {
  const by = new Map();
  for (const r of rows) {
    const k = keyOf(r);
    if (!by.has(k)) by.set(k, []);
    by.get(k).push(r);
  }
  return [...by.entries()].map(([k, rs]) => {
    const x = agg(rs), g = rs[0][C.sgg], mem = [...new Set(rs.map(r => r[C.sgg]))], one = mem.length === 1;
    // PM 기기·주차구역: the distinct units of the members (a 시's 구 may each have their own, or share the 시's)
    const fl = unitsFor(FLEET, mem), pk = unitsFor(PARKU, mem), sv = survey(g), svU = sv && (sv.pub || sv.pri);
    const flPop = fl && !fl.wide ? fl.us.reduce((a, u) => a + (u.pop || 0), 0) : fl?.u.pop;
    const flTot = fl ? (fl.wide ? null : fl.us.reduce((a, u) => a + u.total, 0)) : null;
    const pkN = pk && !pk.wide ? pk.us.reduce((a, u) => a + u.n, 0) : null;
    const pkG = pk ? (pk.wide ? unitGap(pk.u) : parkGap(pkN, pk.us.reduce((a, u) => a + unitArea(u), 0))) : null;
    const t = tripsFor(mem), ag = one ? AGE[g] : ageFor(rs);
    return { sgg: k, name: keyName(k, rs[0]), pop: x.pop, area: x.area, stops: x.stops, n: mem.length,
      v: m.v(x), gap: rs.some(r => r[C.stop_gap]), either: M('either').v(x), good: M('good').v(x), route: rs.every(r => r[C.route_ok]), osm: rs.some(r => r[C.osm_fill]), ...t, pm: M('pm').v(x), pmidx: M('pmidx').v(x), stores: x.storeArea ? x.stores : null,
      firms: IND[g]?.firms ?? null, icity: one ? IND[g]?.city ?? null : null, lh: one ? LH[g]?.units ?? null : mem.reduce((a, q) => a + (LH[q]?.units || 0), 0) || null, y2039: ag?.y2039 ?? null, o70: ag?.o70 ?? null,
      pmops: OPS[g] ?? null, bike: BIKE[g]?.[0] ?? null, bikeKind: BIKE[g]?.[1] || '', ord: ORD[g] || null,
      fl, fleetU: fl?.u || null, fleet: flTot, fleetDate: fl ? [...new Set(fl.us.map(u => u.date))].join(' · ') : '', fleetpc: fl && flPop ? (fl.wide ? fl.u.total : flTot) / flPop * 1000 : null,
      sv, svWide: !!svU && svU.sgg.some(q => !mem.includes(q)), bikes: sv?.bikes != null && svU && !svU.sgg.some(q => !mem.includes(q)) ? sv.bikes : null,
      pmuse: (u => u && u.pop ? u.pm_use / u.pop * 1e4 : null)(sv?.pu), pmuseWide: !!sv?.pu && sv.pu.sgg.some(q => !mem.includes(q)),
      pk, parkU: pk?.u || null, park: pkN, parkd: pkG?.d ?? null, park20: pkG?.gaps[0].short ?? null, park30: pkG?.gaps[1].short ?? null,
      pmord: ORD[g] ? lvOf(ORD[g], 'o') : null, tow: ORD[g]?.t ? (ORD[g].fee ?? 0) : null, btow: ORD[g] ? lvOf(ORD[g], 'b') : null, dpark: ORD[g] ? lvOf(ORD[g], 'p') : null, nokick: ORD[g] ? lvOf(ORD[g], 'n') : null, grace: ORD[g]?.t ? graceMin(ORD[g].grace) : null, move: ORD[g] ? lvOf(ORD[g], 'm') : null, uarea: U[g]?.area ?? null, upop: U[g]?.pop ?? null, ucity: U[g]?.city ?? null };
  });
}

// 교통카드 trips are per whole 시군구 (they do not change with the 동 지역 filter). Where the card data barely covers the
// 시군구 (sparse, or no data at all) the values are left out and shown as '자료 부족' rather than as almost no riders.
function trips(sgg) {
  const t = T[sgg], pop = SGGPOP[sgg];
  if (!t || t.sparse) return { trip: null, transfer: null, elder: null, sparse: true };
  const users = Object.values(t.users).reduce((a, b) => a + b, 0);
  return { trip: pop ? t.day / pop : null, transfer: t.transfer != null && t.day ? t.transfer / t.day : null,
    elder: users && t.users['경로'] != null ? t.users['경로'] / users : null, sparse: false };
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
const NOCARD = '<small title="교통카드 자료가 거의 들어오지 않은 시군구">자료 부족</small>';
function renderSgg(rows, m) {
  $('sgg-title').textContent = (st.tab === 'policy' ? '시군구별 조례·운영 현황' : `시군구 순위 · ${m.name}`) + (st.gu ? ' (일반구로 나눔)' : '');
  const cols = [{ k: 'name', h: '시군구', l: 1, f: (v, r) => esc(v) + (r.osm ? ' <small title="OpenStreetMap 정류장으로 보완">*</small>' : '') + (r.gap ? ' <small title="정류장 위치 자료 부족: 버스 지표 없음">자료 부족</small>' : '') },
    { k: 'v', h: m.name, f: v => mfmt(m, v) }, { k: 'pop', h: '인구', f: fmt }, { k: 'area', h: '면적(㎢)', f: fmt }, { k: 'stops', h: '정류장', f: fmt },
    { k: 'either', h: '버스·철도 도보권 밖', f: pct }, { k: 'good', h: '노선 넉넉한 정류장 도보권 밖', f: pct },
    { k: 'pm', h: 'PM 10분 새로 닿는 면적', f: pct }, { k: 'pmidx', h: 'PM 잠재 지수', f: v => v == null ? '-' : (v * 100).toFixed(1) },
    { k: 'pmops', h: `공유 PM 운영 (${opsDate()})`, f: v => opsText(v) }, { k: 'bike', h: `공유자전거 운영 (${opsDate()})`, f: (v, r) => bikeText(v == null ? null : [v, r.bikeKind]) },
    // a value collected only for a whole 시도 or 시 (서울 PM 기기, 시도별 앱 이용 …) is not repeated as each 구's own:
    // counts show as '서울 전체 18,548대' in grey and sort last, rates as the area's average
    { k: 'fleet', h: 'PM 기기 수', f: (v, r) => v == null ? (r.fl?.wide ? wideTxt(r.fl.u, fmt(r.fl.u.total) + '대') : '-') : fmt(v) + partTag(r.fl) + ` <small>${esc(r.fleetDate)}</small>` },
    { k: 'fleetpc', h: 'PM 기기 (1천 명당)', f: (v, r) => v == null ? '-' : v.toFixed(1) + (r.fl?.wide ? avgTag(r.fl.u) : '') },
    { k: 'bikes', h: `공유자전거 (${meta2()})`, f: (v, r) => v == null ? (r.sv?.bikes != null ? wideTxt(r.sv.pub || r.sv.pri, fmt(r.sv.bikes) + '대') : '-') : fmt(v) },
    { k: 'pmuse', h: 'PM 앱 이용 (1만 명당)', f: (v, r) => v == null ? '-' : v.toFixed(1) + (r.pmuseWide ? avgTag(r.sv.pu) : '') }, { k: 'park', h: 'PM 주차구역', f: (v, r) => v == null ? (r.pk?.wide ? wideTxt(r.pk.u, fmt(r.pk.u.n) + '곳') : '-') : fmt(v) + partTag(r.pk) },
    { k: 'parkd', h: `주차구역 (${st.hab ? '생활권 ' : ''}1㎢당)`, f: (v, r) => v == null ? '-' : v.toFixed(1) + (r.pk?.wide ? avgTag(r.pk.u) : '') },
    { k: 'park20', h: '20곳/㎢ 기준 부족', f: (v, r) => v == null ? '-' : (v > 0 ? pct(v) : '충족') + (r.pk?.wide ? avgTag(r.pk.u) : '') }, { k: 'park30', h: '30곳/㎢ 기준 부족', f: (v, r) => v == null ? '-' : (v > 0 ? pct(v) : '충족') + (r.pk?.wide ? avgTag(r.pk.u) : '') },
    { k: 'pmord', h: 'PM 조례', f: (v, r) => lvText(r.ord, 'o') }, { k: 'move', h: 'PM 조례 이동·견인 근거', f: (v, r) => lvText(r.ord, 'm') }, { k: 'tow', h: 'PM 견인료', f: (v, r) => towText(r.ord) }, { k: 'grace', h: 'PM 견인 유예시간', l: 1, f: (v, r) => r.ord?.t ? graceText(r.ord) : '-' }, { k: 'btow', h: '자전거 견인', f: (v, r) => bikeTow(r.ord) }, { k: 'dpark', h: '지정주차제', f: (v, r) => lvText(r.ord, 'p') }, { k: 'nokick', h: '킥보드 없는 거리', f: (v, r) => lvText(r.ord, 'n') },
    { k: 'stores', h: '상가업소', f: fmt }, { k: 'firms', h: '산업단지 가동업체', f: (v, r) => fmt(v) + (r.icity && v != null ? ` <small title="${esc(r.icity)} 전체 값">시</small>` : '') },
    { k: 'lh', h: 'LH 임대 세대', f: fmt }, { k: 'y2039', h: '20~39세 비중', f: pct }, { k: 'o70', h: '70세 이상 비중', f: pct },
    { k: 'uarea', h: '법정 도시지역 면적', f: (v, r) => pct(v) + (r.ucity && v != null ? ` <small title="${esc(r.ucity)} 전체 값">시</small>` : '') },
    { k: 'upop', h: '도시지역 거주 인구', f: pct },
    { k: 'trip', h: '주민 1인당 하루 승차', f: (v, r) => r.sparse ? NOCARD : v == null ? '-' : v.toFixed(2) },
    { k: 'transfer', h: '환승 통행 비중', f: (v, r) => r.sparse ? NOCARD : pct(v) }, { k: 'elder', h: '경로 승차 비중', f: (v, r) => r.sparse ? NOCARD : pct(v) }];
  const T = TABS[st.tab];
  sggShown = table($('sgg-table'), T.cols ? cols.filter(c => c.k === 'name' || T.cols.includes(c.k)) : cols, sgRows(rows, m), sortSgg, k => { sortSgg = { k, asc: sortSgg.k === k ? !sortSgg.asc : k === 'name' }; render(); },
    r => { pickSggRow(r.sgg); $('dong-title').scrollIntoView({ behavior: 'smooth' }); });
  $('sgg-csv').onclick = () => csv(`시군구_${st.metric}.csv`, ['시군구코드', '시군구', m.name, '인구', '면적_km2', '정류장', '버스철도도보권밖', '노선넉넉한정류장도보권밖', 'PM10분새로닿는면적비율', 'PM잠재지수', '공유PM운영', '공유자전거운영', '공유자전거유형', 'PM조례', 'PM조례이동견인근거', 'PM견인', 'PM견인료', '견인료기준지자체', 'PM견인유예시간', '견인운영비고', '자전거견인', '지정주차제', '킥보드없는거리', 'PM기기수', 'PM기기단위', 'PM기기기준일', 'PM기기1천명당', '공유자전거대수_2024', 'PM앱이용횟수_1만명당_2024', 'PM주차구역', st.hab ? '주차구역_생활권1km2당' : '주차구역_1km2당', '주차구역20곳기준부족률', '주차구역30곳기준부족률', '상가업소', '산업단지가동업체', 'LH임대세대', '20~39세비중', '70세이상비중', '법정도시지역면적비율', '도시지역거주인구비율', '주민1인당하루승차', '환승통행비중', '경로승차비중', '노선수자료', 'OSM보완', '교통카드자료부족'],
    sggShown.map(r => [r.sgg, r.name, r.v, r.pop, r.area.toFixed(3), r.stops, r.either, r.good, r.pm, r.pmidx == null ? null : (r.pmidx * 100).toFixed(1), r.pmops, r.bike, r.bikeKind, r.ord ? lvText(r.ord, 'o') : null, r.ord ? lvText(r.ord, 'm') : null, r.ord ? lvText(r.ord, 't') : null, r.ord?.fee, r.ord?.src, r.ord?.t ? r.ord?.grace : null, r.ord?.note, r.ord ? lvText(r.ord, 'b') : null, r.ord ? lvText(r.ord, 'p') : null, r.ord ? lvText(r.ord, 'n') : null, r.fleet ?? r.fleetU?.total, r.fl?.wide ? r.fleetU?.name : r.name, r.fleetDate, r.fleetpc, r.sv?.bikes ?? null, r.pmuse, r.park ?? r.parkU?.n ?? null, r.parkd, r.park20, r.park30, r.stores, r.firms, r.lh, r.y2039, r.o70, r.uarea, r.upop, r.trip, r.transfer, r.elder, r.route, r.osm, +r.sparse]));
}

function renderDongs(rows, m) {
  const pick = pickSgg ? rows.filter(inPick) : rows;
  const label = pickSgg ? pickName() : (st.sido ? rows[0]?.[C.sidonm] : '전국');
  $('dong-title').textContent = `행정동 · ${label}${pickSgg ? '' : ' (상위 500곳)'}`;
  const data = pick.map(r => { const x = agg([r]); return { code: r[C.code], name: r[C.name], sgg: `${r[C.sidonm]} ${r[C.sggnm]}`, type: r[C.type], pop: r[C.pop], area: r[C.area_km2], stops: r[C.stops], v: m.v(x), either: M('either').v(x), good: M('good').v(x), pm: M('pm').v(x), stores: r[C.stores], pmidx: r[C.pm_index], y2039: r[C.y2039], o70: r[C.o70], i: D.indexOf(r) }; });
  const cols = [{ k: 'name', h: '행정동', l: 1, f: esc }, { k: 'sgg', h: '시군구', l: 1, f: esc }, { k: 'type', h: '구분', l: 1 }, { k: 'v', h: m.name, f: v => mfmt(m, v) },
    { k: 'pop', h: '인구', f: fmt }, { k: 'area', h: '면적(㎢)', f: v => v.toFixed(2) }, { k: 'stops', h: '정류장', f: fmt }, { k: 'either', h: '버스·철도 도보권 밖', f: pct }, { k: 'good', h: '노선 넉넉한 정류장 도보권 밖', f: pct },
    { k: 'pm', h: 'PM 10분 새로 닿는 면적', f: pct }, { k: 'stores', h: '상가업소', f: fmt }, { k: 'pmidx', h: 'PM 잠재 지수', f: v => v == null ? '-' : v.toFixed(1) },
    { k: 'y2039', h: '20~39세', f: pct }, { k: 'o70', h: '70세 이상', f: pct }];
  dongShown = table($('dong-table'), cols, data, sortDong, k => { sortDong = { k, asc: sortDong.k === k ? !sortDong.asc : ['name', 'sgg', 'type'].includes(k) }; renderDongs(D.filter(visible), metric()); },
    r => { zoomTo([D[r.i]]); window.scrollTo({ top: $('map').offsetTop - 10, behavior: 'smooth' }); });
  $('dong-csv').onclick = () => csv(`행정동_${st.metric}.csv`, ['행정동코드', '행정동', '시군구', '구분', m.name, '인구', '면적_km2', '정류장', '버스철도도보권밖', '노선넉넉한정류장도보권밖', 'PM10분새로닿는면적비율', '상가업소', 'PM잠재지수', '20~39세비중', '70세이상비중'],
    dongShown.map(r => [r.code, r.name, r.sgg, r.type, r.v, r.pop, r.area, r.stops, r.either, r.good, r.pm, r.stores, r.pmidx, r.y2039, r.o70]));
}

function csv(name, head, rows) {
  const q = v => v == null ? '' : /[",\n]/.test(String(v)) ? `"${String(v).replace(/"/g, '""')}"` : v;
  const blob = new Blob(['﻿' + [head, ...rows].map(r => r.map(q).join(',')).join('\n')], { type: 'text/csv' });
  const a = Object.assign(document.createElement('a'), { href: URL.createObjectURL(blob), download: name });
  a.click(); URL.revokeObjectURL(a.href);
}

// ── 주목 지역 Top 10 ─────────────────────────────────────────────────────────────────────────────
// The candidates follow the selection: 전국 → its 시군구, a 시도 → the 시군구 in it, a 시군구 → its 읍면동.
// Each lens ranks the candidates on a few factors (tie-aware percentile within the candidates, 0–1) and averages them:
// A 정책 (교통 공백을 PM이 메울 곳), B 사업 (PM 수요가 있을 곳), 종합 = (A + B) / 2. Factors without data are skipped.
const FOCUS_F = {
  either: { n: '대중교통까지 걷기 먼 땅', f: v => pp(v) },
  pm: { n: 'PM 10분이면 닿는 땅', f: v => pp(v) },
  gapPop: { n: '대중교통에서 먼 주민(추정)', f: v => people(v) },
  pmidx: { n: 'PM 잠재 지수', f: v => (v * 100).toFixed(0) },
  young: { n: '20·30대 주민', f: v => people(v) },
  towEase: { n: '견인', f: (v, c) => c.towTxt },
};
const LENS = {
  mix: { name: '종합 (정책 + 사업)', short: '종합' },
  a: { name: '정책: 교통 공백을 PM이 메울 곳', short: '정책', f: ['either', 'pm', 'gapPop'] },
  b: { name: '사업: PM 수요가 있을 곳', short: '사업', f: ['pmidx', 'young', 'pm', 'towEase'] },
};
const lens = () => $('focus-lens')?.value || 'mix';
const people = v => v == null ? '-' : v >= 1e4 ? `약 ${(v / 1e4).toFixed(1)}만 명` : `${fmt(v)}명`;
function towBurden(o) {  // higher = heavier: 견인료 (금액 없으면 3만원으로 봄) + 즉시 견인 1만원 상당
  if (!o?.t) return { v: 0, txt: '견인 없음(부담 낮음)' };
  const g = graceMin(o.grace);
  return { v: (o.fee || 30000) + (g === 0 ? 10000 : 0), txt: (o.fee ? won(o.fee) : '견인') + (o.grace ? ' · ' + graceShort(o.grace) : '') };
}
// candidates of a level: 시군구 (from their 행정동, so the 동 지역 filter and the area basis apply) or 읍면동
function focusCands(rows, level, split = st.gu) {
  const eM = M('either'), pM = M('pm');
  const one = r => { const x = agg([r]), e = eM.v(x); return { e, p: pM.v(x), pop: r[C.pop] || 0, gp: e == null ? null : (r[C.pop] || 0) * e, y: r[C.y2039] == null ? null : (r[C.pop] || 0) * r[C.y2039] }; };
  if (level === 'dong') return rows.filter(r => !r[C.stop_gap]).map(r => { const o = one(r);
    return { key: D.indexOf(r), sgg: r[C.sgg], name: pickSet?.size > 1 ? `${r[C.sggnm].slice(CITY[r[C.sgg]]?.name.length ?? 0)} ${r[C.name]}` : r[C.name], either: o.e, pm: o.p, gapPop: o.gp, pmidx: r[C.pm_index] == null ? null : r[C.pm_index] / 100, young: o.y, towEase: null }; });
  const by = new Map();
  for (const r of rows) { const k = unitKeyOf(r[C.sgg], split); if (!by.has(k)) by.set(k, []); by.get(k).push(r); }
  return [...by.entries()].filter(([, rs]) => !rs.some(r => r[C.stop_gap])).map(([k, rs]) => {
    const x = agg(rs), g = rs[0][C.sgg], tb = towBurden(ORD[g]);
    let gp = 0, y = 0, hasY = false;
    for (const r of rs) { const o = one(r); gp += o.gp || 0; if (o.y != null) { y += o.y; hasY = true; } }
    return { key: k, sgg: g, name: keyName(k, rs[0]), short: CITYK[k]?.name ?? rs[0][C.sggnm], either: eM.v(x), pm: pM.v(x), gapPop: gp,
      pmidx: M('pmidx').v(x), young: hasY ? y : null, towEase: ORD[g] ? -tb.v : null, towTxt: tb.txt };
  });
}
function focusScore(cands) {
  const pr = {};
  for (const k of Object.keys(FOCUS_F)) {
    const v = cands.map(c => c[k]).filter(v => v != null).sort((a, b) => a - b);
    if (v.length < 3 || v[0] === v[v.length - 1]) continue;  // a factor that does not vary (e.g. 견인 within one 시군구) says nothing
    const lo = x => { let a = 0, b = v.length; while (a < b) { const m = (a + b) >> 1; v[m] < x ? a = m + 1 : b = m; } return a; };
    const hi = x => { let a = 0, b = v.length; while (a < b) { const m = (a + b) >> 1; v[m] <= x ? a = m + 1 : b = m; } return a; };
    pr[k] = x => x == null ? null : (lo(x) + hi(x)) / 2 / v.length;
  }
  for (const c of cands) {
    c.p = {};
    for (const k of Object.keys(pr)) c.p[k] = pr[k](c[k]);
    for (const l of ['a', 'b']) { const ps = LENS[l].f.map(k => c.p[k]).filter(v => v != null); c[l] = ps.length >= 2 ? ps.reduce((a, b) => a + b, 0) / ps.length : null; }
    c.mix = c.a != null && c.b != null ? (c.a + c.b) / 2 : null;
  }
  return cands;
}
const ranked = (cands, l) => cands.filter(c => c[l] != null).sort((a, b) => b[l] - a[l]);
const topPct = (i, n) => Math.max(1, Math.ceil((i + 1) / n * 100));
function focusWhy(c, l) {  // the two strongest factors of the lens
  const all = (l === 'mix' ? [...new Set([...LENS.a.f, ...LENS.b.f])] : LENS[l].f).filter(k => c.p?.[k] != null).sort((a, b) => c.p[b] - c.p[a]);
  const ks = all.filter(k => c.p[k] >= 0.6).slice(0, 2);  // only factors where it really stands out
  if (!ks.length && all.length) ks.push(all[0]);
  return ks.map(k => `${FOCUS_F[k].n} ${FOCUS_F[k].f(c[k], c)}`).join(' · ');
}
function focusTags(c) {
  const t = [];
  if (c.towTxt == null) return t;
  if (OPS[c.sgg] === 0) t.push(['warn', '공유 PM 미운영']);
  const bk = Beam.kind(c.sgg);
  if (bk) t.push(['beam', '빔 ' + bk]); else if (Beam.loaded()) t.push(['', '빔 미운영']);
  if (ORD[c.sgg]?.t && graceMin(ORD[c.sgg].grace) === 0) t.push(['warn', '즉시 견인']);
  return t;
}
const nameIn = c => (c.short || c.name);
function focusScope() {
  const scope = D.filter(r => (!st.urban || r[C.type] === '동') && (!st.sido || r[C.sido] === st.sido) && inPick(r));
  const unit = st.gu ? '시군구(일반구 포함)' : '시군구';
  return { scope, level: pickSgg ? 'dong' : 'sgg', where: pickSgg ? `${pickName().replace(/^\S+ /, '')} 안 읍면동` : st.sido ? `${scope[0]?.[C.sidonm] ?? ''} 안 ${unit}` : `전국 ${unit}` };
}
let natCache = null;  // national 시군구 scores, for the rank of a picked 시군구
function natScores() {  // 일반구 picked on its own → rank among 시군구 with 일반구 split
  const split = st.gu || (!!pickKey && !!CITY[pickKey]), k = `${st.urban}|${st.hab}|${split}`;
  if (natCache?.k !== k) natCache = { k, c: focusScore(focusCands(D.filter(r => !st.urban || r[C.type] === '동'), 'sgg', split)) };
  return natCache.c;
}
function renderFocus() {
  const el = $('focus-list');
  if (!el || !D) return;
  const { scope, level, where } = focusScope(), l = lens();
  const cands = focusScore(focusCands(scope, level)), rk = ranked(cands, l).slice(0, 10);
  $('focus-title').textContent = `주목 지역 Top 10 · ${where}${st.urban ? ' (동 지역)' : ''}`;
  $('focus-note').innerHTML = `${esc(LENS[l].name)} 점수 순. ` + (l === 'mix' ? '정책 점수와 사업 점수의 평균입니다. ' : '') +
    `점수는 ${where} ${fmt(cands.length)}곳 안에서 매긴 순위(백분위)의 평균(0~100)입니다. <a href="about.html#focus">산식</a>`;
  el.innerHTML = rk.map((c, i) => `<li><button type="button" data-k="${esc(c.key)}"><span class="fr">${i + 1}</span><span class="fn">${esc(nameIn(c))}` +
    `<small> ${LENS[l].short} ${(c[l] * 100).toFixed(0)}점</small></span><span class="fw">${focusWhy(c, l)}</span>` +
    `<span class="ft">${focusTags(c).map(([k, t]) => `<i class="${k}">${esc(t)}</i>`).join('')}</span></button></li>`).join('') || '<li class="note">점수를 낼 자료가 부족합니다.</li>';
  el.querySelectorAll('button').forEach(b => b.onclick = () => {
    if (level === 'dong') { $('dong').value = b.dataset.k; $('dong').dispatchEvent(new Event('change')); }
    else pickSggRow(b.dataset.k);
  });
}
// the conclusion and the basic facts that open 지역별 인사이트
function renderHead(scope, x) {
  const l = lens(), L = LENS[l], parts = [];
  if (pickSgg) {
    const nat = ranked(natScores(), l), i = nat.findIndex(c => c.key === pickKey), me = nat[i];
    const sido = nat.filter(c => c.sgg.slice(0, 2) === pickSgg.slice(0, 2)), j = sido.findIndex(c => c.key === pickKey);
    if (me) {
      const p = topPct(i, nat.length), verdict = p <= 10 ? '우선 검토' : p <= 30 ? '검토' : '후순위';
      const acts = [];
      if (me.a != null && me.a >= 0.7) acts.push(OPS[pickSgg] === 0 ? '공유 PM이 없는 교통 공백 지역: 지자체에 PM 연계 시범사업을 제안할 근거' : '공백이 큰데 공유 PM은 운영 중: 정류장·역 주변 주차구역과 환승 연계 확충을 제안할 곳');
      if (me.b != null && me.b >= 0.7) acts.push(Beam.loaded() ? (Beam.kind(pickSgg) ? `빔 ${Beam.kind(pickSgg)} 지역: 기기·주차구역 확충 우선` : '빔 미운영: 진출 검토 후보') : 'PM 수요 잠재력이 큰 곳');
      if (ORD[pickSgg]?.t && (graceMin(ORD[pickSgg].grace) === 0 || (ORD[pickSgg].fee || 0) >= 40000)) acts.push('견인 부담이 큰 곳: 유예시간·견인료 협의 대상');
      parts.push(`<div class="verdict"><b>결론: ${verdict} 지역</b><br>${L.short} 점수로 전국 ${fmt(nat.length)}개 시군구 가운데 <b>${i + 1}위</b>` + (j >= 0 ? `, ${esc(scope[0][C.sidonm])} ${sido.length}곳 가운데 ${j + 1}위` : '') + `입니다.` +
        `<br>이유: ${focusWhy(me, l)}` + (acts.length ? `<ul>${acts.map(a => `<li>${a}</li>`).join('')}</ul>` : '') + '</div>');
    }
  } else {
    const rk = ranked(focusScore(focusCands(scope, 'sgg')), l).slice(0, 3);
    if (rk.length) parts.push(`<div class="verdict"><b>결론: ${esc(st.sido ? scope[0][C.sidonm] : '전국')}에서 먼저 볼 곳은 ${rk.map(c => esc(nameIn(c))).join(', ')}</b><br>1위 ${esc(nameIn(rk[0]))}: ${focusWhy(rk[0], l)}. 전체 순위는 위 Top 10에 있습니다.</div>`);
  }
  // 기본 현황
  const allSggs = [...new Set(scope.map(r => r[C.sgg]))], sggs = [...new Map(scope.map(r => [unitKeyOf(r[C.sgg]), r[C.sgg]])).values()], e = M('either').v(x), A = st.hab ? x.hab : x.area, chip = [];
  if (e != null) chip.push(['대중교통까지 걷기 먼 땅', `${e * A < 10 ? (e * A).toFixed(1) : fmt(e * A)}㎢`, `${st.hab ? '생활권' : '전체'} 면적의 ${pp(e)}`]);
  if (pickSgg) {
    const P = pickRow(scope), sv = P.sv;
    // a count kept only for a whole 시도·시 is not this 시군구's own: say so instead of showing it as if it were
    const cnt = (x, own, wideN, unit) => !x ? ['자료 없음', ''] : x.wide ? ['시군구별 자료 없음', `${esc(unitShort(x.u))} 전체 ${fmt(wideN)}${unit}`] : [`${fmt(own)}${unit}`, x.partial ? '일부 구만' : ''];
    const [fv, fs] = cnt(P.fl, P.fleet, P.fl?.u.total, '대'), [kv, ks] = cnt(P.pk, P.park, P.pk?.u.n, '곳');
    const [bv, bs] = sv?.bikes == null ? ['자료 없음', ''] : P.svWide ? ['시군구별 자료 없음', `${esc(unitShort(sv.pub || sv.pri))} 전체 ${fmt(sv.bikes)}대`] : [`${fmt(sv.bikes)}대`, ''];
    chip.push(['PM 기기', fv, [fs, P.fleetDate ? esc(P.fleetDate) : ''].filter(Boolean).join(' · ')]);
    chip.push(['공유자전거', bv, [bs, sv?.bikes != null ? meta2() : ''].filter(Boolean).join(' · ')]);
    chip.push(['PM 주차구역', kv, [ks, P.parkd != null ? `1㎢당 ${P.parkd.toFixed(1)}곳` : ''].filter(Boolean).join(' · ')]);
    chip.push(['공유 PM', OPS[pickSgg] == null ? '-' : OPS[pickSgg] ? '운영' : '미운영', opsDate()]);
    if (Beam.loaded()) chip.push(['빔모빌리티', Beam.kind(pickSgg) || '미운영', '']);
  } else {
    const units = [...new Set(allSggs.map(g => FLEET[g]).filter(Boolean))].filter(u => !u.partial);
    chip.push(['PM 기기', units.length ? `${fmt(units.reduce((a, u) => a + u.total, 0))}대` : '자료 없음', units.length ? `자료 있는 ${units.length}개 지역 합계` : '']);
    const pus = [...new Set(allSggs.map(g => PARKU[g]).filter(Boolean))];
    chip.push(['PM 주차구역', pus.length ? `${fmt(pus.reduce((a, u) => a + u.n, 0))}곳` : '자료 없음', pus.length ? `자료 있는 ${pus.length}개 지역 합계` : '']);
    const off = sggs.filter(g => OPS[g] === 0).length;
    chip.push(['공유 PM 미운영', `${off}곳`, `시군구 ${sggs.length}곳 중 · ${opsDate()}`]);
    if (Beam.loaded()) { const d = sggs.filter(g => Beam.kind(g) === '직영').length, f = sggs.filter(g => Beam.kind(g) === '프랜차이즈').length;
      chip.push(['빔 운영 시군구', `${d + f}곳`, `직영 ${d} · 프랜차이즈 ${f}`]); }
  }
  $('ins-head').innerHTML = parts.join('') + `<div class="chips">${chip.map(([t, v, s]) => `<div class="chip"><span class="kt">${t}</span><b>${v}</b>${s ? `<small>${s}</small>` : ''}</div>`).join('')}</div>`;
}

main().catch(e => { $('summary').textContent = '자료를 불러오지 못했습니다: ' + e.message; console.error(e); });
