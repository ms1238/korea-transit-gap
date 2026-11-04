'use strict';
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

let D, C, GEO, T, U, IND, LH, AGE, OPS, SGGPOP, meta, map, sortSgg = { k: 'v', asc: false }, sortDong = { k: 'v', asc: false }, pickSgg = null;
const NARROW = window.matchMedia('(max-width: 640px)').matches;  // phones: legend and layer list start folded
const st = { metric: 'either', sido: '', urban: false, hab: true, legend: !NARROW, insMore: false };
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
  const [stats, geo] = await Promise.all([fetch('data/stats.json').then(r => r.json()), fetch('data/dongs.geojson').then(r => r.json())]);
  D = stats.rows; meta = stats.meta; T = stats.sgg_trips || {}; U = stats.sgg_urban || {}; IND = stats.sgg_industrial || {}; LH = stats.sgg_lh || {}; AGE = stats.sgg_age || {}; OPS = stats.sgg_pm_ops || {}; C = Object.fromEntries(stats.cols.map((c, i) => [c, i]));
  SGGPOP = {};
  for (const r of D) SGGPOP[r[C.sgg]] = (SGGPOP[r[C.sgg]] || 0) + (r[C.pop] || 0);
  $('asof').textContent = `기준: 정류장 위치 ${meta.stops_collected} 수집 · 정차 노선수 ${meta.route_days.length ? meta.route_days.map(d => d.slice(0, 4) + '-' + d.slice(4, 6) + '-' + d.slice(6)).join(', ') + ' 운행일' : '수집 중'}${meta.upis_year ? ' · 도시계획현황 ' + meta.upis_year + '년' : ''}${meta.trips_months.length ? ' · 교통카드 통행 ' + meta.trips_months.map(m => m.slice(0, 4) + '년 ' + +m.slice(4) + '월').join(', ') : ''} · 인구 ${meta.pop_ym.slice(0, 4)}년 ${+meta.pop_ym.slice(4)}월 · 행정동 경계 ${meta.boundary.replace('ver', '')}`;
  for (const m of METRICS) $('metric').add(new Option(m.name, m.id));
  const sidos = [...new Map(D.map(r => [r[C.sido], r[C.sidonm]])).entries()].sort((a, b) => a[0].localeCompare(b[0]));
  for (const [c, n] of sidos) $('sido').add(new Option(n, c));
  $('metric').onchange = e => { st.metric = e.target.value; render(); };
  $('sido').onchange = e => { st.sido = e.target.value; pickSgg = null; fillSgg(); render(); zoomTo(D.filter(r => !st.sido || r[C.sido] === st.sido)); };
  $('sgg').onchange = e => pickSggRow(e.target.value || null);
  $('dong').onchange = e => {
    const i = +e.target.value;
    if (e.target.value === '' || !map) return;
    zoomTo([D[i]]);
    const c = GEO.features[i].geometry, ring = c.type === 'Polygon' ? c.coordinates[0] : c.coordinates[0][0];
    const ll = ring.reduce((p, q) => [p[0] + q[0] / ring.length, p[1] + q[1] / ring.length], [0, 0]);
    new maplibregl.Popup({ maxWidth: '300px' }).setLngLat(ll).setHTML(dongPopup(D[i])).addTo(map);
  };
  fillSgg();
  $('urban').onchange = e => { st.urban = e.target.checked; render(); };
  $('layers').open = !NARROW;
  const showLegend = on => { st.legend = on; $('legend').hidden = !on; $('legend-btn').hidden = on; };
  $('legend-btn').onclick = () => showLegend(true);
  $('legend').onclick = e => { if (e.target.closest('.legend-x')) showLegend(false); };
  showLegend(st.legend);
  $('ins-more').onclick = () => { st.insMore = !st.insMore; renderInsights(); };
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
    $('show-3d').onchange = () => {
      const on = $('show-3d').checked;
      map.setTerrain(on ? { source: 'dem-3d', exaggeration: 1.6 } : null);
      map.easeTo({ pitch: on ? 60 : 0, bearing: on ? map.getBearing() : 0, duration: 800 });
      legend(metric());
    };
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
    map.addSource('pmgrid', { type: 'image', url: 'data/pmgrid.png', coordinates: [meta.grid_bounds[0], [meta.grid_bounds[1][0], meta.grid_bounds[0][1]], meta.grid_bounds[1], [meta.grid_bounds[0][0], meta.grid_bounds[1][1]]] });
    map.addLayer({ id: 'pmgrid', type: 'raster', source: 'pmgrid', paint: { 'raster-opacity': 0.85, 'raster-resampling': 'nearest' } }, 'stops');
    for (const [id, layer] of [['show-stops', 'stops'], ['show-rail', 'rail'], ['show-grid', 'pmgrid']]) {
      const set = () => { map.setLayoutProperty(layer, 'visibility', $(id).checked ? 'visible' : 'none'); if (id === 'show-grid') legend(metric()); };
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
    line('주민등록인구', fmt(r[C.pop])) + line('면적 (생활권)', r[C.area_km2].toFixed(2) + '㎢ (' + pct(r[C.hab]) + ')') + line('버스 정류장', fmt(r[C.stops]) + '곳') +
    METRICS.map(m => line(m.name, mfmt(m, m.v(x)))).join('') + (OPS[r[C.sgg]] != null ? line(`공유 PM (시군구, ${opsDate()})`, opsText(OPS[r[C.sgg]])) : '') + (r[C.stores] != null ? line('상가업소', fmt(r[C.stores]) + '곳') : '') + (r[C.y2039] != null ? line('20~39세 / 70세 이상', pct(r[C.y2039]) + ' / ' + pct(r[C.o70])) : '') + (U[r[C.sgg]] ? line(`법정 도시지역 면적 (${U[r[C.sgg]].city ? esc(U[r[C.sgg]].city) + ' 전체' : '시군구'})`, pct(U[r[C.sgg]].area)) : '') + (() => { const t = trips(r[C.sgg]); return t.sparse ? line('교통카드 승차 (시군구)', '자료 부족') : t.trip == null ? '' :
      line('주민 1인당 하루 승차 (시군구)', t.trip.toFixed(2)) + line('환승 통행 비중 (시군구)', pct(t.transfer)); })() + '</table>' +
    (r[C.stop_gap] ? '<small>이 시군구는 국토부 파일과 OpenStreetMap 모두 정류장이 크게 부족해 버스 지표를 비워 두었습니다.</small><br>' : '') +
    (r[C.osm_fill] ? '<small>이 시군구는 국토부 정류장 파일에 거의 없어 OpenStreetMap 정류장으로 보완했습니다.</small><br>' : '') +
    (r[C.route_ok] ? '' : '<small>이 시군구는 정차 노선수 자료가 없거나 정류장 연결이 부족합니다.</small>');
}

// 시도 → 시군구 → 읍면동 drill-down
function fillSgg() {
  const sel = $('sgg');
  sel.length = 1;
  if (st.sido) for (const [c, n] of [...new Map(D.filter(r => r[C.sido] === st.sido).map(r => [r[C.sgg], r[C.sggnm]])).entries()].sort((a, b) => a[1].localeCompare(b[1]))) sel.add(new Option(n, c));
  sel.disabled = !st.sido;
  fillDong();
}

function fillDong() {
  const sel = $('dong');
  sel.length = 1;
  if (pickSgg) D.forEach((r, i) => { if (r[C.sgg] === pickSgg) sel.add(new Option(r[C.name], i)); });
  sel.disabled = !pickSgg;
}

function pickSggRow(sgg) {
  pickSgg = sgg;
  if (sgg && !st.sido) { st.sido = D.find(r => r[C.sgg] === sgg)[C.sido]; $('sido').value = st.sido; fillSgg(); render(); }
  $('sgg').value = sgg || '';
  fillDong();
  renderDongs(D.filter(visible), metric());
  renderInsights();
  zoomTo(D.filter(d => sgg ? d[C.sgg] === sgg : !st.sido || d[C.sido] === st.sido));
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

// plain-language findings for the current selection (시도 / 시군구, 동 지역 filter)
function renderInsights() {
  const pmM = M('pm'), goodM = M('good'), busM = M('bus');
  const scope = D.filter(r => (!st.urban || r[C.type] === '동') && (!st.sido || r[C.sido] === st.sido) && (!pickSgg || r[C.sgg] === pickSgg));
  if (!scope.length) { $('insights').innerHTML = ''; return; }
  const name = pickSgg ? `${scope[0][C.sidonm]} ${scope[0][C.sggnm]}` : st.sido ? scope[0][C.sidonm] : '전국';
  $('ins-title').textContent = `지역별 인사이트 · ${name}${st.urban ? ' 동 지역' : ''}`;
  const x = agg(scope), li = [];
  const nat = agg(D.filter(r => !st.urban || r[C.type] === '동'));
  if (x.pmArea) li.push(`${basis()}으로 보면 <b>${pct(x.walk / x.pmArea)}</b>는 걸어서 정류장·역에 닿고, <b>${pct((x.pm5 + x.pm10) / x.pmArea)}</b>는 걷기엔 멀지만 PM으로 10분 안에 닿습니다. PM 거리지만 경사가 급한 곳 ${pct(x.steep / x.pmArea)}, PM으로도 먼 곳 ${pct(x.far / x.pmArea)}입니다.`
    + (name !== '전국' && nat.pmArea ? ` (전국${st.urban ? ' 동 지역' : ''} PM 10분권 ${pct((nat.pm5 + nat.pm10) / nat.pmArea)})` : ''));
  const top = (list, k, n, f) => list.filter(r => r[k] != null).sort((a, b) => b[k] - a[k]).slice(0, n).map(f).join(', ');
  if (!pickSgg) {
    const sg = sgRows(scope, pmM).filter(r => !r.gap);
    const t1 = top(sg, 'pm', 3, r => `${esc(r.name.replace(/^\S+ /, ''))} ${pct(r.pm)}`);
    if (t1) li.push(`PM이 첫·마지막 구간을 메울 땅이 넓은 시군구: <b>${t1}</b>`);
    const t2 = top(sg, 'pmidx', 3, r => `${esc(r.name.replace(/^\S+ /, ''))} ${(r.pmidx * 100).toFixed(0)}`);
    if (t2) li.push(`PM 잠재 지수(인구·상가 밀도까지 반영)가 높은 시군구: <b>${t2}</b>`);
    const nOff = new Set(scope.filter(r => OPS[r[C.sgg]] === 0).map(r => r[C.sgg])).size;
    if (Object.keys(OPS).length && nOff) {
      const t5 = top(sg.filter(r => r.pmops === 0), 'pm', 3, r => `${esc(r.name.replace(/^\S+ /, ''))} ${pct(r.pm)}`);
      li.push(`공유 PM이 운영되지 않는 시군구(${opsDate()} 기준) ${nOff}곳` + (t5 ? ` 가운데 PM 10분권이 넓은 곳: <b>${t5}</b>` : ''));
    } else if (Object.keys(OPS).length) li.push(`이 범위의 시군구는 모두 공유 PM이 운영 중입니다(${opsDate()} 기준).`);
    const t3 = top(sg, 'either', 3, r => `${esc(r.name.replace(/^\S+ /, ''))} ${pct(r.either)}`);
    if (t3) li.push(`버스·철도 어디에도 걸어서 닿기 어려운 땅이 넓은 시군구: <b>${t3}</b>`);
    const t4 = top(sg, 'good', 3, r => `${esc(r.name.replace(/^\S+ /, ''))} ${pct(r.good)}`);
    if (t4) li.push(`노선이 ${meta.good_routes}개 이상인 정류장까지 걸어서 닿기 어려운 땅이 넓은 시군구: <b>${t4}</b>`);
  } else {
    const sidoX = agg(D.filter(r => (!st.urban || r[C.type] === '동') && r[C.sido] === scope[0][C.sido]));
    const v = pmM.v(x), sv = pmM.v(sidoX);
    if (v != null && sv != null) li.push(`PM 10분 안에 새로 닿는 땅의 비율은 ${pct(v)}로, ${esc(scope[0][C.sidonm])} 평균(${pct(sv)})보다 <b>${v > sv ? '높습니다' : '낮습니다'}</b>.`);
    const dt = top(scope, C.pm_index, 3, r => `${esc(r[C.name])} ${r[C.pm_index].toFixed(0)}`);
    if (dt) li.push(`이 시군구에서 PM 잠재 지수가 높은 읍면동: <b>${dt}</b>`);
    const dg = top(scope.filter(r => r[K('walk')] != null).map(r => Object.assign([...r], { pmv: r[K('pm5')] + r[K('pm10')] })), 'pmv', 3, r => `${esc(r[C.name])} ${pct(r.pmv)}`);
    if (dg) li.push(`PM 10분권 비율이 높은 읍면동: <b>${dg}</b>`);
    const g = goodM.v(x), b = busM.v(x);
    if (g != null) li.push(`노선이 ${meta.good_routes}개 이상인 정류장 도보권 밖 면적은 ${pct(g)}입니다` + (b != null && g - b >= 0.005 ? ` (그 가운데 ${pct(g - b)}p는 정류장은 가까워도 노선이 1~${meta.good_routes - 1}개뿐인 땅).` : '.'));
    const t = trips(pickSgg), ag = AGE[pickSgg];
    if (ag) li.push(`20~39세 주민 비중 ${pct(ag.y2039)}, 70세 이상 ${pct(ag.o70)}` + (t.elder != null ? ` · 교통카드 승차 가운데 경로 비중 ${pct(t.elder)}` : '') + '.');
    if (t.sparse) li.push(`<small>이 시군구는 교통카드 자료가 거의 들어오지 않아(주민 1인당 하루 승차 ${(meta.trips_min ?? 0.02).toFixed(2)}회 미만이거나 자료 없음) 승차·환승·경로 값을 '자료 부족'으로 표시합니다. 실제 이용이 없는 것이 아닙니다.</small>`);
    if (OPS[pickSgg] != null) li.push(OPS[pickSgg] ? `공유 PM이 운영되는 지자체입니다(${opsDate()} 기준).` : `<b>공유 PM이 운영되지 않는 지자체입니다</b>(${opsDate()} 기준).` + (pmM.v(x) ? ' 위 PM 10분권은 서비스가 들어오면 메울 수 있는 공백입니다.' : ''));
    if (IND[pickSgg]) li.push(`산업단지 ${IND[pickSgg].n}곳(가동업체 ${fmt(IND[pickSgg].firms)}곳${IND[pickSgg].city ? ', ' + esc(IND[pickSgg].city) + ' 전체' : ''})은 출퇴근 목적지로, 역과 떨어져 있으면 PM 연계 후보입니다.`);
  }
  const gaps = [...new Set(scope.filter(r => r[C.stop_gap]).map(r => r[C.sggnm]))], noRoute = new Set(scope.filter(r => !r[C.route_ok]).map(r => r[C.sgg])).size;
  const noCard = pickSgg ? 0 : new Set(scope.filter(r => trips(r[C.sgg]).sparse).map(r => r[C.sgg])).size;
  if (gaps.length) li.push(`<small>정류장 위치 자료가 부족해 버스 지표를 뺀 곳: ${gaps.map(esc).join(', ')}</small>`);
  if (noRoute) li.push(`<small>정차 노선수 자료가 없거나 수집 중인 시군구 ${noRoute}곳은 노선 관련 지표가 비어 있습니다.</small>`);
  if (noCard) li.push(`<small>교통카드 자료가 거의 없는 시군구 ${noCard}곳은 승차·환승 값을 '자료 부족'으로 표시합니다.</small>`);
  const cut = NARROW && !st.insMore ? 3 : li.length;
  $('insights').innerHTML = li.slice(0, cut).map(s => `<li>${s}</li>`).join('');
  $('ins-more').hidden = !NARROW || li.length <= 3;
  $('ins-more').textContent = st.insMore ? '접기' : `더 보기 (${li.length - 3})`;
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
  $('legend').innerHTML = `<div class="t"><span>${esc(m.name)}</span><button class="legend-x" type="button" aria-label="범례 닫기">×</button></div>` + scale + stops +
    ($('show-grid').checked ? '<div class="row" style="margin-top:4px"><b>PM 연계 격자</b> <small>(도보권은 투명)</small></div>' + grid.map(([c, t]) => row(c, t)).join('') : '') +
    ($('show-noops').checked ? `<div class="row" style="margin-top:4px"><i style="background:repeating-linear-gradient(135deg,#2e2d2a 0 1.5px,transparent 1.5px 5px)"></i>공유 PM 미운영 시군구 (${opsDate()})</div>` : '') +
    ($('show-terrain').checked || $('show-3d').checked ? `<div class="row" style="margin-top:4px"><small>${$('show-terrain').checked ? '지형 음영: 짙을수록 급한 경사. ' : ''}${$('show-3d').checked ? '3D: 높이 1.6배 과장, 나침반을 누르면 정북으로.' : ''}</small></div>` : '') +
    `<div class="row"><small>정류장은 확대(줌 10 이상)하면 보입니다.</small></div>`;
}

const opsDate = () => meta.pm_ops_date ? `${meta.pm_ops_date.slice(0, 4)}년 말` : '';
const opsText = v => v == null ? '-' : v ? '운영' : '<b>미운영</b>';

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
      v: m.v(x), gap: rs[0][C.stop_gap], either: M('either').v(x), good: M('good').v(x), route: rs[0][C.route_ok], osm: rs[0][C.osm_fill], ...trips(rs[0][C.sgg]), pm: M('pm').v(x), pmidx: M('pmidx').v(x), stores: x.storeArea ? x.stores : null,
      firms: IND[rs[0][C.sgg]]?.firms ?? null, icity: IND[rs[0][C.sgg]]?.city ?? null, lh: LH[rs[0][C.sgg]]?.units ?? null, y2039: AGE[rs[0][C.sgg]]?.y2039 ?? null, o70: AGE[rs[0][C.sgg]]?.o70 ?? null,
      pmops: OPS[rs[0][C.sgg]] ?? null, uarea: U[rs[0][C.sgg]]?.area ?? null, upop: U[rs[0][C.sgg]]?.pop ?? null, ucity: U[rs[0][C.sgg]]?.city ?? null };
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
  $('sgg-title').textContent = `시군구 순위 · ${m.name}`;
  const cols = [{ k: 'name', h: '시군구', l: 1, f: (v, r) => esc(v) + (r.osm ? ' <small title="OpenStreetMap 정류장으로 보완">*</small>' : '') + (r.gap ? ' <small title="정류장 위치 자료 부족: 버스 지표 없음">자료 부족</small>' : '') },
    { k: 'v', h: m.name, f: v => mfmt(m, v) }, { k: 'pop', h: '인구', f: fmt }, { k: 'area', h: '면적(㎢)', f: fmt }, { k: 'stops', h: '정류장', f: fmt },
    { k: 'either', h: '버스·철도 도보권 밖', f: pct }, { k: 'good', h: '노선 넉넉한 정류장 도보권 밖', f: pct },
    { k: 'pm', h: 'PM 10분 새로 닿는 면적', f: pct }, { k: 'pmidx', h: 'PM 잠재 지수', f: v => v == null ? '-' : (v * 100).toFixed(1) },
    { k: 'pmops', h: `공유 PM 운영 (${opsDate()})`, f: v => opsText(v) },
    { k: 'stores', h: '상가업소', f: fmt }, { k: 'firms', h: '산업단지 가동업체', f: (v, r) => fmt(v) + (r.icity && v != null ? ` <small title="${esc(r.icity)} 전체 값">시</small>` : '') },
    { k: 'lh', h: 'LH 임대 세대', f: fmt }, { k: 'y2039', h: '20~39세 비중', f: pct }, { k: 'o70', h: '70세 이상 비중', f: pct },
    { k: 'uarea', h: '법정 도시지역 면적', f: (v, r) => pct(v) + (r.ucity && v != null ? ` <small title="${esc(r.ucity)} 전체 값">시</small>` : '') },
    { k: 'upop', h: '도시지역 거주 인구', f: pct },
    { k: 'trip', h: '주민 1인당 하루 승차', f: (v, r) => r.sparse ? NOCARD : v == null ? '-' : v.toFixed(2) },
    { k: 'transfer', h: '환승 통행 비중', f: (v, r) => r.sparse ? NOCARD : pct(v) }, { k: 'elder', h: '경로 승차 비중', f: (v, r) => r.sparse ? NOCARD : pct(v) }];
  sggShown = table($('sgg-table'), cols, sgRows(rows, m), sortSgg, k => { sortSgg = { k, asc: sortSgg.k === k ? !sortSgg.asc : k === 'name' }; render(); },
    r => { pickSggRow(r.sgg); $('dong-title').scrollIntoView({ behavior: 'smooth' }); });
  $('sgg-csv').onclick = () => csv(`시군구_${st.metric}.csv`, ['시군구코드', '시군구', m.name, '인구', '면적_km2', '정류장', '버스철도도보권밖', '노선넉넉한정류장도보권밖', 'PM10분새로닿는면적비율', 'PM잠재지수', '공유PM운영', '상가업소', '산업단지가동업체', 'LH임대세대', '20~39세비중', '70세이상비중', '법정도시지역면적비율', '도시지역거주인구비율', '주민1인당하루승차', '환승통행비중', '경로승차비중', '노선수자료', 'OSM보완', '교통카드자료부족'],
    sggShown.map(r => [r.sgg, r.name, r.v, r.pop, r.area.toFixed(3), r.stops, r.either, r.good, r.pm, r.pmidx == null ? null : (r.pmidx * 100).toFixed(1), r.pmops, r.stores, r.firms, r.lh, r.y2039, r.o70, r.uarea, r.upop, r.trip, r.transfer, r.elder, r.route, r.osm, +r.sparse]));
}

function renderDongs(rows, m) {
  const pick = pickSgg ? rows.filter(r => r[C.sgg] === pickSgg) : rows;
  const label = pickSgg ? `${pick[0]?.[C.sidonm] ?? ''} ${pick[0]?.[C.sggnm] ?? ''}` : (st.sido ? rows[0]?.[C.sidonm] : '전국');
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

main().catch(e => { $('summary').textContent = '자료를 불러오지 못했습니다: ' + e.message; console.error(e); });
