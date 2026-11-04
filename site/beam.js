'use strict';
// 빔모빌리티 운영지역 (scripts/static/beam_areas.csv → data/beam.geojson, one outline per 시군구): 직영 and 프랜차이즈
// in two colours, a checkbox #show-beam on every page. Beam.kind(sgg) → '직영' | '프랜차이즈' | undefined.
const Beam = (() => {
  const COL = { '직영': '#1d4ed8', '프랜차이즈': '#0d9488' };
  let data = null, kinds = {};
  const ready = fetch('data/beam.geojson').then(r => r.ok ? r.json() : null).then(d => {
    data = d;
    for (const f of d?.features || []) kinds[f.properties.sgg] = f.properties.kind;
  }).catch(() => {});
  const on = () => !!document.getElementById('show-beam')?.checked;
  async function add(map, onChange) {
    await ready;
    if (!data || !map || map.getSource('beam')) return;
    map.addSource('beam', { type: 'geojson', data });
    const color = ['match', ['get', 'kind'], '프랜차이즈', COL['프랜차이즈'], COL['직영']];
    const before = map.getStyle().layers.find(l => l.type === 'symbol')?.id;
    map.addLayer({ id: 'beam-fill', type: 'fill', source: 'beam', layout: { visibility: 'none' }, paint: { 'fill-color': color, 'fill-opacity': 0.12 } }, before);
    map.addLayer({ id: 'beam-line', type: 'line', source: 'beam', layout: { visibility: 'none', 'line-join': 'round' }, paint: {
      'line-color': color, 'line-width': ['interpolate', ['linear'], ['zoom'], 6, 1.6, 11, 3] } }, before);
    map.addLayer({ id: 'beam-line-fr', type: 'line', source: 'beam', filter: ['==', ['get', 'kind'], '프랜차이즈'], layout: { visibility: 'none' }, paint: {
      'line-color': '#ffffff', 'line-width': ['interpolate', ['linear'], ['zoom'], 6, 0.8, 11, 1.4], 'line-dasharray': [2, 2] } }, before);
    const box = document.getElementById('show-beam');
    const set = () => { for (const id of ['beam-fill', 'beam-line', 'beam-line-fr']) map.setLayoutProperty(id, 'visibility', on() ? 'visible' : 'none'); onChange?.(); };
    if (box) box.addEventListener('change', set);
    set();
  }
  const counts = () => { const c = { '직영': 0, '프랜차이즈': 0 }; for (const k of Object.values(kinds)) c[k]++; return c; };
  const legendRows = () => !on() || !data ? '' : '<div class="row" style="margin-top:4px"><b>빔모빌리티 운영지역</b></div>' +
    Object.entries(counts()).map(([k, n]) => `<div class="row"><i style="background:${COL[k]}33;border:2px ${k === '프랜차이즈' ? 'dashed' : 'solid'} ${COL[k]}"></i>${k} ${n}곳</div>`).join('');
  return { add, kind: g => kinds[g], ready, legendRows, on };
})();
