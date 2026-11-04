'use strict';
// 20·30대(20~39세) 인구 상위 10·20·30% 읍면동 (전국 3,559개 읍면동 가운데 순위), checkboxes #young-10/20/30 and the basis
// select #young-basis ('n' 인구수 = 비중 × 주민등록 인구, 's' 비중) on every page. The 'dongs' source has one feature per
// stats.json row (feature id = row index). With several boxes ticked the tighter tiers are drawn darker.
const Young = (() => {
  const P = [10, 20, 30], COL = ['#be123c', '#e11d48', '#fb7185'];
  let rows, ci, map, onChange, rank = [], by = {};
  const ticked = () => P.filter(p => document.getElementById('young-' + p)?.checked);
  const basis = () => document.getElementById('young-basis')?.value || 'n';
  function ranks() {  // top share (0–1] of each 읍면동 among those with age data, by 인구수 (n) and by 비중 (s)
    for (const b of ['n', 's']) {
      const v = rows.map(r => r[ci.y2039] == null || !r[ci.pop] ? null : b === 's' ? r[ci.y2039] : r[ci.y2039] * r[ci.pop]);
      const idx = v.map((x, i) => i).filter(i => v[i] != null).sort((a, c) => v[c] - v[a]);
      by[b] = new Array(rows.length).fill(null);
      idx.forEach((i, k) => { by[b][i] = (k + 1) / idx.length; });
    }
    rank = by[basis()];
  }
  const tier = i => { const t = ticked(); if (!t.length || rank[i] == null) return -1; const k = t.findIndex(p => rank[i] <= p / 100); return k < 0 ? -1 : k; };
  function paint() {
    if (!map?.getLayer('young-line')) return;
    const t = ticked();
    rows.forEach((_, i) => map.setFeatureState({ source: 'dongs', id: i }, { yt: tier(i) }));
    const col = k => COL[P.indexOf(t[k])] ?? COL[2];
    const match = (vals, other) => ['match', ['coalesce', ['feature-state', 'yt'], -1], ...t.flatMap((_, k) => [k, vals(k)]), other];
    if (t.length) {
      map.setPaintProperty('young-fill', 'fill-color', match(col, 'rgba(0,0,0,0)'));
      map.setPaintProperty('young-line', 'line-color', match(col, 'rgba(0,0,0,0)'));
    }
    for (const id of ['young-fill', 'young-line']) map.setLayoutProperty(id, 'visibility', t.length ? 'visible' : 'none');
    onChange?.();
  }
  function init(m, statsRows, colIndex, cb) {  // colIndex: {column name: index} of stats.json rows
    rows = statsRows; ci = colIndex; map = m; onChange = cb;
    ranks();
    const before = map.getStyle().layers.find(l => l.type === 'symbol')?.id;
    map.addLayer({ id: 'young-fill', type: 'fill', source: 'dongs', layout: { visibility: 'none' }, paint: { 'fill-color': 'rgba(0,0,0,0)', 'fill-opacity': 0.35 } }, before);
    map.addLayer({ id: 'young-line', type: 'line', source: 'dongs', layout: { visibility: 'none' }, paint: { 'line-color': 'rgba(0,0,0,0)',
      'line-width': ['interpolate', ['linear'], ['zoom'], 6, 0.6, 11, 2] } }, before);
    for (const p of P) document.getElementById('young-' + p)?.addEventListener('change', paint);
    document.getElementById('young-basis')?.addEventListener('change', () => { rank = by[basis()]; paint(); });
    paint();
  }
  const label = () => basis() === 's' ? '20~39세 비중' : '20~39세 인구수';
  const legendRows = () => { const t = ticked(); if (!t.length || !rows) return '';
    const n = k => rows.filter((_, i) => tier(i) === k).length;
    return `<div class="row" style="margin-top:4px"><b>${label()} 상위 읍면동</b></div>` +
      t.map((p, k) => `<div class="row"><i style="background:${COL[P.indexOf(p)]}88;border:1.5px solid ${COL[P.indexOf(p)]}"></i>${k ? `상위 ${t[k - 1]}~${p}%` : `상위 ${p}%`} (${n(k).toLocaleString('ko-KR')}곳)</div>`).join('') +
      '<div class="row"><small>전국 읍면동 순위, 주민등록 인구 기준</small></div>'; };
  const rankText = (i, b) => by[b]?.[i] == null ? '-' : `상위 ${Math.max(1, Math.ceil(by[b][i] * 100))}%`;
  return { init, legendRows, rankText, paint };
})();
