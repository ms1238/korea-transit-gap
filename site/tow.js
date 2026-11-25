'use strict';
// 서울 PM 견인 신고 (data/seoul_tow.json, built from scripts/static/seoul_tow.csv): one column per field, d = days since
// meta.start. Everything is counted in the browser so any 기간 / 단위 / 구 / 구역 works without another file.
const DV = (document.currentScript?.src.match(/[?&]v=([\w-]+)/) || [])[1];
const dv = u => DV ? `${u}?v=${DV}` : u;
const $ = id => document.getElementById(id);
const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const fmt = n => n == null || isNaN(n) ? '-' : Math.round(n).toLocaleString('ko-KR');
const pct = (a, b) => b ? (a / b * 100).toFixed(1) + '%' : '-';
const fmtMin = m => m == null || isNaN(m) ? '-' : m < 1 ? '1분 미만' : m < 60 ? `${Math.round(m)}분` : m < 1440 ? (r => `${Math.floor(r / 60)}시간${r % 60 ? ` ${r % 60}분` : ''}`)(Math.round(m)) : `${(m / 1440).toFixed(1)}일`;
const SVGNS = 'http://www.w3.org/2000/svg';
const DAY = 864e5;

// 상태 (meta.status order): 견인, 운영사 수거·이동, 처리시간 경과, 기기 미발견, 미처리
const SCOL = ['#f47230', '#257de0', '#b9b8b2', '#00b894', '#dedcd6'];
const STACK = [1, 0, 3, 2, 4];  // bottom → top: the two actions first, then the rest
const RAMP = ['#fde3d0', '#f9b98f', '#f08a4f', '#d4572a', '#9c3417'];  // sequential orange (same as the 안전 page)
const HIST = [[0, 5, '5분 미만'], [5, 15, '5~15분'], [15, 30, '15~30분'], [30, 60, '30분~1시간'], [60, 120, '1~2시간'], [120, 360, '2~6시간'], [360, 1440, '6~24시간'], [1440, Infinity, '24시간 이상']];

let T, N, C, S, MONTH, WEEK, MAXD, map, mapReady = false, playing = null, tsort = { k: 'n', asc: false };
const st = { a: 0, b: 0, unit: 'm', gu: '', kind: '', tl: 'off', cur: 0, metric: 'n', stat: 'med' };
let periods = [], rangeIdx = [];

const dayDate = d => new Date(Date.parse(T.meta.start) + d * DAY);
const iso = d => dayDate(d).toISOString().slice(0, 10);
const dayOf = s => Math.round((Date.parse(s) - Date.parse(T.meta.start)) / DAY);

async function main() {
  T = await fetch(dv('data/seoul_tow.json')).then(r => r.json());
  C = T.cols; N = C.d.length; S = T.meta.status;
  MAXD = C.d[N - 1];
  MONTH = new Int32Array(MAXD + 1); WEEK = new Int32Array(MAXD + 1);
  const wd0 = (dayDate(0).getUTCDay() + 6) % 7;  // Monday = 0
  for (let d = 0; d <= MAXD; d++) { const x = dayDate(d); MONTH[d] = x.getUTCFullYear() * 12 + x.getUTCMonth(); WEEK[d] = Math.floor((d + wd0) / 7); }
  st.a = 0; st.b = MAXD;
  $('asof').textContent = `${T.meta.start} ~ ${T.meta.end} · 신고 ${fmt(N)}건`;
  for (const id of ['from', 'to']) { $(id).min = T.meta.start; $(id).max = T.meta.end; }
  T.gu.forEach((g, i) => $('gu').add(new Option(g, i)));
  quickButtons();
  $('from').onchange = e => { const d = dayOf(e.target.value); if (!isNaN(d)) { st.a = clamp(d, 0, st.b); render(); } };
  $('to').onchange = e => { const d = dayOf(e.target.value); if (!isNaN(d)) { st.b = clamp(d, st.a, MAXD); render(); } };
  $('unit').onchange = e => { st.unit = e.target.value; render(); };
  $('gu').onchange = e => { st.gu = e.target.value; render(); };
  $('kind').onchange = e => { st.kind = e.target.value; render(); };
  $('metric').onchange = e => { st.metric = e.target.value; renderSel(); };
  $('stat').onchange = e => { st.stat = e.target.value; render(); };
  document.querySelectorAll('[data-tl]').forEach(b => b.onclick = () => setTl(b.dataset.tl));
  $('play').onclick = togglePlay;
  $('cursor').oninput = e => { st.cur = +e.target.value; stopPlay(); renderCursor(); };
  $('csv').onclick = downloadCsv;
  legend($('main-legend'), STACK.map(s => [SCOL[s], S[s]]));
  legend($('dur-legend'), [[SCOL[0], '견인'], [SCOL[1], '운영사 수거·이동']]);
  legend($('hist-legend'), [[SCOL[0], '견인'], [SCOL[1], '운영사 수거·이동']]);
  initMap();
  render();
  let rt; addEventListener('resize', () => { clearTimeout(rt); rt = setTimeout(render, 150); });
}
const clamp = (x, a, b) => Math.max(a, Math.min(b, x));

function quickButtons() {
  const y0 = dayDate(0).getUTCFullYear(), y1 = dayDate(MAXD).getUTCFullYear();
  const items = [['전체', 0, MAXD], ['최근 12개월', Math.max(0, MAXD - 364), MAXD]];
  for (let y = y0; y <= y1; y++) items.push([String(y), Math.max(0, dayOf(`${y}-01-01`)), Math.min(MAXD, dayOf(`${y}-12-31`))]);
  $('quick').innerHTML = items.map(([t], i) => `<button type="button" data-q="${i}">${t}</button>`).join('');
  $('quick').onclick = e => { const i = e.target.dataset.q; if (i == null) return; [, st.a, st.b] = items[i]; render(); };
}

const pid = d => st.unit === 'd' ? d : st.unit === 'w' ? WEEK[d] : MONTH[d];
const baseOk = i => (st.gu === '' || C.g[i] === +st.gu) && (st.kind === '' || C.k[i] === +st.kind);

function periodLabel(p, short) {
  const x = dayDate(p.d0), y = x.getUTCFullYear(), m = x.getUTCMonth() + 1, d = x.getUTCDate();
  if (st.unit === 'm') return short ? `${String(y).slice(2)}.${String(m).padStart(2, '0')}` : `${y}년 ${m}월`;
  const s = `${short ? String(y).slice(2) : y}.${String(m).padStart(2, '0')}.${String(d).padStart(2, '0')}`;
  return st.unit === 'w' && !short ? `${s} 주 (~${iso(p.d1).slice(5).replace('-', '.')})` : s;
}

// --- the range: periods with their counts and durations ---------------------------------------------------------
function render() {
  $('from').value = iso(st.a); $('to').value = iso(st.b);
  document.querySelectorAll('#quick button').forEach(b => b.classList.remove('on'));
  periods = [];
  for (let d = st.a; d <= st.b; d++) {
    const id = pid(d);
    if (!periods.length || periods[periods.length - 1].id !== id) periods.push({ id, d0: d, d1: d, c: [0, 0, 0, 0, 0], dur: [[], []] });
    else periods[periods.length - 1].d1 = d;
  }
  const at = new Map(periods.map((p, i) => [p.id, i]));
  rangeIdx = [];
  for (let i = 0; i < N; i++) {
    const d = C.d[i];
    if (d < st.a || d > st.b || !baseOk(i)) continue;
    rangeIdx.push(i);
    const p = periods[at.get(pid(d))], s = C.s[i];
    p.c[s]++;
    if (s < 2 && C.m[i] != null) p.dur[s].push(C.m[i]);
  }
  const cur = $('cursor');
  cur.max = Math.max(0, periods.length - 1);
  st.cur = clamp(st.cur, 0, periods.length - 1);
  cur.value = st.cur;
  $('main-title').textContent = `${st.gu === '' ? '서울' : T.gu[+st.gu]}${st.kind === '' ? '' : st.kind === '1' ? ' · 즉시 견인 구역' : ' · 일반 구역'} ${{ d: '일별', w: '주별', m: '월별' }[st.unit]} 신고 건수와 처리 결과`;
  drawMain(); drawBrush(); drawDur();
  renderCursor();
}

function selRange() {
  if (st.tl === 'off' || !periods.length) return [st.a, st.b];
  const p = periods[st.cur];
  return st.tl === 'one' ? [p.d0, p.d1] : [st.a, p.d1];
}

function renderCursor() {
  const p = periods[st.cur];
  $('tl-label').textContent = st.tl === 'off' || !p ? '타임라인 꺼짐' : st.tl === 'one' ? periodLabel(p) : `${iso(st.a)} ~ ${periodLabel(p)}`;
  $('cursor').value = st.cur;
  document.querySelectorAll('#c-main .cur').forEach(el => el.remove());
  if (st.tl !== 'off' && p) mark($('c-main'), st.cur);
  document.querySelectorAll('#c-dur .curl').forEach(el => el.remove());
  if (st.tl !== 'off' && p) markLine($('c-dur'), st.cur);
  renderSel();
}

// --- the selection (whole range, or the timeline's point): KPIs, map, small charts, table --------------------------
function renderSel() {
  const [a, b] = selRange();
  const idx = rangeIdx.filter(i => C.d[i] >= a && C.d[i] <= b);
  const c = [0, 0, 0, 0, 0], dur = [[], []];
  for (const i of idx) { c[C.s[i]]++; if (C.s[i] < 2 && C.m[i] != null) dur[C.s[i]].push(C.m[i]); }
  const n = idx.length;
  $('kpis').innerHTML = [
    ['신고', fmt(n), `${iso(a)} ~ ${iso(b)}`],
    ['견인', fmt(c[0]), pct(c[0], n)],
    ['운영사 수거·이동', fmt(c[1]), pct(c[1], n)],
    ['처리시간 경과 (무조치)', fmt(c[2]), pct(c[2], n)],
    ['견인까지 (중앙값)', fmtMin(median(dur[0])), `평균 ${fmtMin(mean24(dur[0]))} · 24시간 넘는 건 제외`],
    ['수거까지 (중앙값)', fmtMin(median(dur[1])), `평균 ${fmtMin(mean24(dur[1]))} · 24시간 넘는 건 제외`],
  ].map(([t, v, s]) => `<div class="kpi"><div class="kt">${t}</div><div class="kv">${v}</div><div class="ks">${s}</div></div>`).join('');
  drawMap(idx);
  drawHist(dur);
  drawKind(idx);
  drawBy(idx);
  drawHour(idx);
  drawTable(idx, a, b);
  const f5 = dur[0].filter(m => m < 5).length;
  $('dur-note').textContent = dur[0].length ? `고른 시점 견인 ${fmt(dur[0].length)}건 가운데 ${pct(f5, dur[0].length)}(${fmt(f5)}건)는 신고 후 5분 안에 견인됐습니다. 평균은 며칠씩 걸린 소수 기록에 크게 끌려가므로 24시간 넘는 건을 빼고 냅니다. 한 시점에 3건 미만이면 선을 끊습니다.` : '';
}

function median(a) {
  if (!a.length) return null;
  const s = Float64Array.from(a).sort(), h = s.length >> 1;
  return s.length % 2 ? s[h] : (s[h - 1] + s[h]) / 2;
}
function mean24(a) { const x = a.filter(m => m <= 1440); return x.length ? x.reduce((p, q) => p + q, 0) / x.length : null; }

// --- svg helpers ------------------------------------------------------------------------------------------------
function svg(el, h) {
  el.innerHTML = '';
  const w = Math.max(280, el.clientWidth);
  const s = document.createElementNS(SVGNS, 'svg');
  s.setAttribute('viewBox', `0 0 ${w} ${h}`); s.setAttribute('width', w); s.setAttribute('height', h);
  el.appendChild(s);
  return [s, w];
}
function node(parent, tag, attrs, text) {
  const e = document.createElementNS(SVGNS, tag);
  for (const k in attrs) e.setAttribute(k, attrs[k]);
  if (text != null) e.textContent = text;
  parent.appendChild(e);
  return e;
}
function nice(v) { if (v <= 0) return 1; const p = 10 ** Math.floor(Math.log10(v)), f = v / p; return (f <= 1 ? 1 : f <= 2 ? 2 : f <= 5 ? 5 : 10) * p; }
function yAxis(s, w, M, h, max, f) {
  for (const t of [0, max / 2, max]) {
    const y = h - M.b - (h - M.t - M.b) * t / max;
    node(s, 'line', { x1: M.l, x2: w - M.r, y1: y, y2: y, class: t ? 'grid' : 'base' });
    node(s, 'text', { x: M.l - 6, y: y + 4, class: 'ax', 'text-anchor': 'end' }, f(t));
  }
}
function xTicks(s, M, h, n, x, label, bw) {
  const every = Math.max(1, Math.ceil(n / Math.max(2, Math.floor((x(n) - x(0)) / 64))));
  for (let i = 0; i < n; i += every) node(s, 'text', { x: x(i) + bw / 2, y: h - M.b + 16, class: 'ax', 'text-anchor': 'middle' }, label(i));
}
function legend(el, items) { el.innerHTML = items.map(([c, t]) => `<span><i style="background:${c}"></i>${esc(t)}</span>`).join(''); }

const tip = () => $('tip');
function showTip(e, html) {
  const t = tip(); t.innerHTML = html; t.hidden = false;
  const r = t.getBoundingClientRect(), x = e.clientX + 14 + r.width > innerWidth ? e.clientX - r.width - 14 : e.clientX + 14;
  t.style.left = x + 'px'; t.style.top = Math.max(4, e.clientY - r.height - 10) + 'px';
}
const hideTip = () => { tip().hidden = true; };
const tipRows = rows => rows.map(([c, k, v]) => `<div class="tr">${c ? `<i style="background:${c}"></i>` : ''}<span>${esc(k)}</span><b>${v}</b></div>`).join('');

// stacked bars: labels[i], counts[i][s]; onPick(i) on click
function stackBars(el, h, n, counts, label, tipTitle, onPick) {
  const [s, w] = svg(el, h), M = { l: 46, r: 8, t: 8, b: 24 };
  const tot = counts.map(c => c.reduce((p, q) => p + q, 0));
  const max = nice(Math.max(1, ...tot));
  const step = (w - M.l - M.r) / Math.max(1, n), gap = step > 6 ? Math.min(2, step * 0.2) : 0, bw = Math.max(0.6, step - gap);
  const x = i => M.l + i * step, y = v => (h - M.t - M.b) * v / max;
  yAxis(s, w, M, h, max, fmt);
  for (let i = 0; i < n; i++) {
    let base = h - M.b;
    const segs = STACK.filter(k => counts[i][k]);
    segs.forEach((k, j) => {
      const hh = y(counts[i][k]); if (hh <= 0) return;
      const top = j === segs.length - 1, r = top && bw >= 6 ? Math.min(3, bw / 2, hh) : 0, sep = !top && hh > 3 && bw > 3 ? 1 : 0;
      base -= hh;
      node(s, 'path', { d: r ? `M${x(i)},${base + hh - sep}V${base + r}q0,${-r} ${r},${-r}H${x(i) + bw - r}q${r},0 ${r},${r}V${base + hh - sep}Z` : `M${x(i)},${base + hh - sep}V${base}H${x(i) + bw}V${base + hh - sep}Z`, fill: SCOL[k] });
    });
  }
  xTicks(s, M, h, n, x, label, bw);
  const hit = node(s, 'rect', { x: M.l, y: M.t, width: w - M.l - M.r, height: h - M.t - M.b, fill: 'transparent', style: onPick ? 'cursor:pointer' : '' });
  const hover = node(s, 'rect', { y: M.t, height: h - M.t - M.b, width: step, class: 'hov', visibility: 'hidden' });
  const at = e => clamp(Math.floor((e.clientX - s.getBoundingClientRect().left - M.l) / step), 0, n - 1);
  hit.addEventListener('mousemove', e => {
    const i = at(e); hover.setAttribute('x', x(i)); hover.setAttribute('visibility', 'visible');
    showTip(e, `<div class="tt">${esc(tipTitle(i))}</div>` + tipRows([...STACK].reverse().filter(k => counts[i][k]).map(k => [SCOL[k], S[k], `${fmt(counts[i][k])} (${pct(counts[i][k], tot[i])})`])) + tipRows([[null, '합계', fmt(tot[i])]]));
  });
  hit.addEventListener('mouseleave', () => { hover.setAttribute('visibility', 'hidden'); hideTip(); });
  if (onPick) hit.addEventListener('click', e => onPick(at(e)));
  el._geo = { x, step, M, h, bw };
}

function drawMain() {
  stackBars($('c-main'), 230, periods.length, periods.map(p => p.c), i => periodLabel(periods[i], true), i => periodLabel(periods[i]),
    i => { if (st.tl === 'off') setTl('one'); st.cur = i; stopPlay(); renderCursor(); });
}
function mark(el, i) {
  const g = el._geo; if (!g) return;
  const s = el.querySelector('svg');
  const r = node(s, 'rect', { x: g.x(i) - 1, y: g.M.t - 2, width: g.step + 2, height: g.h - g.M.t - g.M.b + 4, class: 'cur' });
  s.insertBefore(r, s.firstChild);
}

// overview strip over the whole span with the chosen range as a brush
function drawBrush() {
  const el = $('c-brush'), h = 58, [s, w] = svg(el, h), M = { l: 46, r: 8, t: 4, b: 18 };
  const months = [], mi = new Map();
  for (let d = 0; d <= MAXD; d++) if (!mi.has(MONTH[d])) { mi.set(MONTH[d], months.length); months.push({ d0: d, n: 0 }); }
  for (let i = 0; i < N; i++) if (baseOk(i)) months[mi.get(MONTH[C.d[i]])].n++;
  const max = Math.max(1, ...months.map(m => m.n));
  const X = d => M.l + (w - M.l - M.r) * d / (MAXD + 1), Y = v => h - M.b - (h - M.t - M.b) * v / max;
  let p = `M${X(0)},${h - M.b}`;
  months.forEach((m, k) => { const d1 = k + 1 < months.length ? months[k + 1].d0 : MAXD + 1; p += `L${X(m.d0)},${Y(m.n)}L${X(d1)},${Y(m.n)}`; });
  node(s, 'path', { d: p + `L${X(MAXD + 1)},${h - M.b}Z`, class: 'brush-area' });
  node(s, 'line', { x1: M.l, x2: w - M.r, y1: h - M.b, y2: h - M.b, class: 'base' });
  const y0 = dayDate(0).getUTCFullYear(), y1 = dayDate(MAXD).getUTCFullYear();
  for (let y = y0; y <= y1; y++) { const d = dayOf(`${y}-01-01`); if (d >= 0) node(s, 'text', { x: X(d) + 3, y: h - 4, class: 'ax' }, y); }
  const sel = node(s, 'rect', { y: M.t, height: h - M.t - M.b, class: 'brush-sel' });
  const ha = node(s, 'rect', { y: M.t, height: h - M.t - M.b, width: 8, rx: 3, class: 'brush-h' });
  const hb = node(s, 'rect', { y: M.t, height: h - M.t - M.b, width: 8, rx: 3, class: 'brush-h' });
  let a = st.a, b = st.b;
  const place = () => { sel.setAttribute('x', X(a)); sel.setAttribute('width', Math.max(1, X(b + 1) - X(a))); ha.setAttribute('x', X(a) - 4); hb.setAttribute('x', X(b + 1) - 4); };
  place();
  const dAt = e => clamp(Math.floor((e.clientX - s.getBoundingClientRect().left - M.l) / (w - M.l - M.r) * (MAXD + 1)), 0, MAXD);
  let drag = null;
  s.addEventListener('pointerdown', e => {
    const d = dAt(e), px = e.clientX - s.getBoundingClientRect().left;
    drag = Math.abs(px - X(a)) < 8 ? { k: 'a' } : Math.abs(px - X(b + 1)) < 8 ? { k: 'b' } : d > a && d < b && b - a < MAXD ? { k: 'm', o: d - a, len: b - a } : { k: 'n', o: d };
    if (drag.k === 'n') { a = b = d; }
    s.setPointerCapture(e.pointerId); place(); e.preventDefault();
  });
  s.addEventListener('pointermove', e => {
    const d = dAt(e), px = e.clientX - s.getBoundingClientRect().left;
    s.style.cursor = drag?.k === 'm' ? 'grabbing' : Math.abs(px - X(a)) < 8 || Math.abs(px - X(b + 1)) < 8 ? 'ew-resize' : 'crosshair';
    if (!drag) return;
    if (drag.k === 'a') a = Math.min(d, b); else if (drag.k === 'b') b = Math.max(d, a);
    else if (drag.k === 'm') { a = clamp(d - drag.o, 0, MAXD - drag.len); b = a + drag.len; }
    else { a = Math.min(drag.o, d); b = Math.max(drag.o, d); }
    place();
    $('from').value = iso(a); $('to').value = iso(b);
  });
  s.addEventListener('pointerup', () => { if (!drag) return; drag = null; st.a = a; st.b = b; render(); });
}

// duration lines: median (or mean of those within 24 h) per period, 견인 and 운영사 수거
function drawDur() {
  const el = $('c-dur'), h = 210, [s, w] = svg(el, h), M = { l: 64, r: 8, t: 8, b: 24 };
  const f = st.stat === 'med' ? median : mean24;
  const val = [0, 1].map(k => periods.map(p => p.dur[k].length >= 3 ? f(p.dur[k]) : null));
  // log scale: 견인 takes minutes and 수거 hours, so a linear axis flattens one of them
  const vs = val.flat().filter(v => v != null);
  const TICKS = [1, 5, 15, 60, 180, 720, 1440, 4320];
  const lo = Math.max(1, Math.min(...vs, 60)), hi = Math.max(...vs, 10);
  const t0 = [...TICKS].reverse().find(t => t <= lo) ?? 1, t1 = TICKS.find(t => t >= hi) ?? hi;
  const n = periods.length, step = (w - M.l - M.r) / Math.max(1, n);
  const L = v => Math.log(Math.max(v, t0)), x = i => M.l + (i + 0.5) * step, y = v => h - M.b - (h - M.t - M.b) * (L(v) - L(t0)) / (L(t1) - L(t0));
  for (const t of TICKS.filter(t => t >= t0 && t <= t1)) {
    node(s, 'line', { x1: M.l, x2: w - M.r, y1: y(t), y2: y(t), class: t === t0 ? 'base' : 'grid' });
    node(s, 'text', { x: M.l - 6, y: y(t) + 4, class: 'ax', 'text-anchor': 'end' }, fmtMin(t));
  }
  for (const k of [1, 0]) {
    let d = '', pen = false;
    val[k].forEach((v, i) => { if (v == null) { pen = false; return; } d += `${pen ? 'L' : 'M'}${x(i).toFixed(1)},${y(v).toFixed(1)}`; pen = true; });
    node(s, 'path', { d, fill: 'none', stroke: SCOL[k], 'stroke-width': 2, 'stroke-linejoin': 'round' });
    if (n <= 40) val[k].forEach((v, i) => v != null && node(s, 'circle', { cx: x(i), cy: y(v), r: 2.5, fill: SCOL[k], stroke: '#fff', 'stroke-width': 1 }));
  }
  xTicks(s, M, h, n, i => M.l + i * step, i => periodLabel(periods[i], true), step);
  const hit = node(s, 'rect', { x: M.l, y: M.t, width: w - M.l - M.r, height: h - M.t - M.b, fill: 'transparent' });
  const cross = node(s, 'line', { y1: M.t, y2: h - M.b, class: 'cross', visibility: 'hidden' });
  const dots = [0, 1].map(k => node(s, 'circle', { r: 4, fill: SCOL[k], stroke: '#fff', 'stroke-width': 2, visibility: 'hidden' }));
  hit.addEventListener('mousemove', e => {
    const i = clamp(Math.floor((e.clientX - s.getBoundingClientRect().left - M.l) / step), 0, n - 1);
    cross.setAttribute('x1', x(i)); cross.setAttribute('x2', x(i)); cross.setAttribute('visibility', 'visible');
    [0, 1].forEach(k => { const v = val[k][i]; dots[k].setAttribute('visibility', v == null ? 'hidden' : 'visible'); if (v != null) { dots[k].setAttribute('cx', x(i)); dots[k].setAttribute('cy', y(v)); } });
    const p = periods[i];
    showTip(e, `<div class="tt">${esc(periodLabel(p))}</div>` + tipRows([0, 1].map(k => [SCOL[k], S[k], `${fmtMin(val[k][i])} <small>(${fmt(p.dur[k].length)}건)</small>`])));
  });
  hit.addEventListener('mouseleave', () => { cross.setAttribute('visibility', 'hidden'); dots.forEach(d => d.setAttribute('visibility', 'hidden')); hideTip(); });
  el._geo = { x: i => M.l + i * step, step, M, h };
}
function markLine(el, i) {
  const g = el._geo; if (!g) return;
  const s = el.querySelector('svg');
  const l = node(s, 'rect', { x: g.x(i), y: g.M.t, width: g.step, height: g.h - g.M.t - g.M.b, class: 'curl' });
  s.insertBefore(l, s.firstChild);
}

// --- small charts -------------------------------------------------------------------------------------------------
function drawHist(dur) {
  const tot = dur.map(a => a.length);
  const cnt = dur.map(a => HIST.map(([lo, hi]) => a.filter(m => m >= lo && m < hi).length));
  const max = Math.max(0.0001, ...cnt.flatMap((c, k) => c.map(v => tot[k] ? v / tot[k] : 0)));
  $('hist-sub').textContent = `견인 ${fmt(tot[0])}건 · 수거 ${fmt(tot[1])}건 각각의 비율`;
  $('c-hist').innerHTML = HIST.map(([, , l], j) => `<div class="hrow"><span class="bl">${l}</span><div class="hb">${[0, 1].map(k =>
    `<div class="hbar" title="${esc(S[k])} ${fmt(cnt[k][j])}건 (${pct(cnt[k][j], tot[k])})"><i style="width:${(tot[k] ? cnt[k][j] / tot[k] / max * 100 : 0).toFixed(1)}%;background:${SCOL[k]}"></i><em>${pct(cnt[k][j], tot[k])}</em></div>`).join('')}</div></div>`).join('');
}

function share100(label, c) {
  const n = c.reduce((p, q) => p + q, 0);
  return `<div class="srow"><span class="bl">${esc(label)} <small>${fmt(n)}건</small></span><div class="sbar">${STACK.filter(k => c[k]).map(k =>
    `<i style="flex:${c[k]};background:${SCOL[k]}" title="${esc(S[k])} ${fmt(c[k])}건 (${pct(c[k], n)})"></i>`).join('')}</div><span class="sv">견인 ${pct(c[0], n)} · 수거 ${pct(c[1], n)}</span></div>`;
}
function drawKind(idx) {
  const c = [[0, 0, 0, 0, 0], [0, 0, 0, 0, 0]];
  for (const i of idx) c[C.k[i]][C.s[i]]++;
  $('c-kind').innerHTML = share100('즉시 견인 구역', c[1]) + share100('일반 구역', c[0]) + `<div class="legend-inline">${STACK.map(k => `<span><i style="background:${SCOL[k]}"></i>${esc(S[k])}</span>`).join('')}</div>`;
}
function drawBy(idx) {
  const c = [0, 0, 0, 0];
  for (const i of idx) if (C.s[i] === 0) c[C.b[i]]++;
  const n = c.reduce((p, q) => p + q, 0), max = Math.max(1, ...c);
  $('c-by').innerHTML = [[2, '견인업체'], [3, '구청'], [0, '기록 없음']].filter(([k]) => c[k] || k !== 0).map(([k, l]) =>
    `<div class="bar"><span class="bl">${l}</span><span class="bt"><i style="width:${(c[k] / max * 100).toFixed(1)}%;background:${SCOL[0]}"></i></span><span class="bv">${pct(c[k], n)}</span></div>`).join('');
}
function drawHour(idx) {
  const c = Array.from({ length: 24 }, () => [0, 0, 0, 0, 0]);
  for (const i of idx) c[C.h[i]][C.s[i]]++;
  stackBars($('c-hour'), 150, 24, c, i => `${i}시`, i => `${i}시~${i + 1}시 신고`);
}

// --- map ----------------------------------------------------------------------------------------------------------
function initMap() {
  map = new maplibregl.Map({ container: 'map', style: 'https://tiles.openfreemap.org/styles/positron', center: [127.0, 37.55], zoom: 10.4, attributionControl: { compact: true } });
  map.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'top-right');
  map.on('load', () => {
    const before = map.getStyle().layers.find(l => l.type === 'symbol')?.id;
    if (T.bounds) {
      map.addSource('gu', { type: 'geojson', data: T.bounds });
      map.addLayer({ id: 'gu-line', type: 'line', source: 'gu', paint: { 'line-color': '#8a8984', 'line-width': 0.8 } }, before);
    }
    map.addSource('cells', { type: 'geojson', data: { type: 'FeatureCollection', features: [] } });
    map.addLayer({ id: 'cells', type: 'circle', source: 'cells', paint: {
      'circle-radius': ['get', 'r'], 'circle-color': ['get', 'col'], 'circle-opacity': 0.8,
      'circle-stroke-color': '#fff', 'circle-stroke-width': 0.6 } });
    const pop = new maplibregl.Popup({ closeButton: false, closeOnClick: false, maxWidth: '260px' });
    map.on('mousemove', 'cells', e => {
      const p = e.features[0].properties, c = JSON.parse(p.c);
      map.getCanvas().style.cursor = 'pointer';
      pop.setLngLat(e.lngLat).setHTML(`<div class="tt">신고 ${fmt(p.n)}건 <small>(약 200 m 칸)</small></div>` + tipRows(STACK.filter(k => c[k]).reverse().map(k => [SCOL[k], S[k], `${fmt(c[k])} (${pct(c[k], p.n)})`])) + (p.md !== 'null' && p.md != null ? tipRows([[null, '견인까지 중앙값', fmtMin(+p.md)]]) : '')).addTo(map);
    });
    map.on('mouseleave', 'cells', () => { map.getCanvas().style.cursor = ''; pop.remove(); });
    mapReady = true;
    renderSel();
  });
}

function drawMap(idx) {
  const agg = new Map();
  for (const i of idx) {
    const c = C.c[i]; if (c == null) continue;
    let a = agg.get(c); if (!a) agg.set(c, a = { n: 0, c: [0, 0, 0, 0, 0], m: [] });
    a.n++; a.c[C.s[i]]++; if (C.s[i] === 0 && C.m[i] != null) a.m.push(C.m[i]);
  }
  const max = Math.max(1, ...[...agg.values()].map(a => a.n));
  const tow = st.metric === 't', MIN = 5;
  const feats = [...agg.entries()].sort((p, q) => q[1].n - p[1].n).map(([c, a]) => {
    const r = a.c[0] / a.n;
    return { type: 'Feature', geometry: { type: 'Point', coordinates: T.cells[c] },
      properties: { n: a.n, c: JSON.stringify(a.c), md: median(a.m), r: 2.5 + 13 * Math.sqrt(a.n / max),
        col: !tow ? '#257de0' : a.n < MIN ? '#c9c8c3' : RAMP[Math.min(4, Math.floor(r * 5))] } };
  });
  if (mapReady) map.getSource('cells').setData({ type: 'FeatureCollection', features: feats.reverse() });
  $('legend').innerHTML = `<div class="t"><span>${tow ? '견인 비율 (칸별)' : '신고 건수 (칸별)'}</span></div>` +
    (tow ? `<div class="bar">${RAMP.map(c => `<i style="background:${c}"></i>`).join('')}</div><div class="bar-l"><span>0%</span><span>50%</span><span>100%</span></div><div class="row"><i class="pt" style="background:#c9c8c3"></i>신고 ${MIN}건 미만</div>`
      : `<div class="row"><i class="pt" style="background:#257de0"></i>원 크기 = 신고 건수 (가장 많은 칸 ${fmt(max)}건)</div>`) +
    `<div class="row"><small>${fmt(agg.size)}칸 · 약 200 m 칸으로 묶음</small></div>`;
}

// --- table ----------------------------------------------------------------------------------------------------------
let tableRows = [];
function drawTable(idx, a, b) {
  const by = new Map();
  for (const i of idx) {
    const g = C.g[i]; let r = by.get(g);
    if (!r) by.set(g, r = { g, n: 0, c: [0, 0, 0, 0, 0], m: [[], []] });
    r.n++; r.c[C.s[i]]++; if (C.s[i] < 2 && C.m[i] != null) r.m[C.s[i]].push(C.m[i]);
  }
  tableRows = [...by.values()].map(r => ({ gu: r.g == null ? '(구 정보 없음)' : T.gu[r.g], g: r.g, n: r.n, t: r.c[0], tp: r.c[0] / r.n, cp: r.c[1] / r.n, ep: r.c[2] / r.n, np: r.c[3] / r.n, tm: median(r.m[0]), cm: median(r.m[1]) }));
  const cols = [['gu', '구'], ['n', '신고'], ['t', '견인'], ['tp', '견인 비율'], ['cp', '운영사 수거 비율'], ['ep', '처리시간 경과 비율'], ['np', '기기 미발견 비율'], ['tm', '견인까지'], ['cm', '수거까지']];
  const k = tsort.k, dir = tsort.asc ? 1 : -1;
  tableRows.sort((p, q) => k === 'gu' ? dir * p.gu.localeCompare(q.gu) : dir * ((p[k] ?? -1) - (q[k] ?? -1)));
  const f = (c, r) => c === 'gu' ? esc(r.gu) : c === 'n' || c === 't' ? fmt(r[c]) : c.endsWith('m') ? fmtMin(r[c]) : (r[c] * 100).toFixed(1) + '%';
  $('tbl-title').textContent = `구별 (${iso(a)} ~ ${iso(b)})`;
  $('table').innerHTML = `<thead><tr>${cols.map(([c, h]) => `<th data-k="${c}" class="${c === k ? 'on' : ''}" ${c === 'gu' ? 'style="text-align:left"' : ''}>${h}</th>`).join('')}</tr></thead><tbody>` +
    tableRows.map(r => `<tr data-g="${r.g ?? ''}" class="${st.gu !== '' && +st.gu === r.g ? 'sel' : ''}">${cols.map(([c]) => `<td ${c === 'gu' ? 'style="text-align:left"' : ''}>${f(c, r)}</td>`).join('')}</tr>`).join('') + '</tbody>';
  $('table').querySelectorAll('th').forEach(th => th.onclick = () => { tsort = { k: th.dataset.k, asc: tsort.k === th.dataset.k ? !tsort.asc : th.dataset.k === 'gu' }; renderSel(); });
  $('table').querySelectorAll('tbody tr').forEach(tr => tr.onclick = () => { const g = tr.dataset.g; if (g === '') return; st.gu = st.gu === g ? '' : g; $('gu').value = st.gu; render(); });
}
function downloadCsv() {
  const [a, b] = selRange();
  const head = ['구', '신고', '견인', '견인비율', '운영사수거비율', '처리시간경과비율', '기기미발견비율', '견인까지_중앙값_분', '수거까지_중앙값_분'];
  const q = v => v == null ? '' : typeof v === 'number' ? +v.toFixed(4) : `"${String(v).replace(/"/g, '""')}"`;
  const body = tableRows.map(r => [r.gu, r.n, r.t, r.tp, r.cp, r.ep, r.np, r.tm, r.cm].map(q).join(','));
  const blob = new Blob(['﻿' + [head.join(','), ...body].join('\n')], { type: 'text/csv' });
  const l = document.createElement('a'); l.href = URL.createObjectURL(blob); l.download = `서울견인_구별_${iso(a)}_${iso(b)}.csv`; l.click();
}

// --- timeline ---------------------------------------------------------------------------------------------------------
function setTl(m) {
  st.tl = m;
  document.querySelectorAll('[data-tl]').forEach(b => { b.classList.toggle('on', b.dataset.tl === m); b.setAttribute('aria-checked', b.dataset.tl === m); });
  $('play').disabled = $('cursor').disabled = m === 'off';
  if (m === 'off') stopPlay();
  renderCursor();
}
function togglePlay() {
  if (playing) return stopPlay();
  if (st.cur >= periods.length - 1) st.cur = 0;
  $('play').textContent = '❚❚ 멈춤';
  playing = setInterval(() => { if (st.cur >= periods.length - 1) return stopPlay(); st.cur++; renderCursor(); }, st.unit === 'd' ? 150 : 450);
}
function stopPlay() { clearInterval(playing); playing = null; $('play').textContent = '▶ 재생'; }

main().catch(e => { $('asof').textContent = '자료를 불러오지 못했습니다: ' + e.message; console.error(e); });
