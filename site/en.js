'use strict';
// English tables for HQ: the dashboard's status and regulation figures per municipality (기초지자체; 일반구 merged into
// their city), from the same data files as the Korean pages. Romanization is automatic (Revised Romanization with the
// main sound-change rules), shown next to the Korean name.
const DV = (document.currentScript?.src.match(/[?&]v=([\w-]+)/) || [])[1];
const dv = u => DV ? `${u}?v=${DV}` : u;
const $ = id => document.getElementById(id);
const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const num = (v, d = 0) => v == null ? '' : Number(v).toLocaleString('en-US', { maximumFractionDigits: d, minimumFractionDigits: d });
const pct = v => v == null ? '' : (v * 100).toFixed(1) + '%';

// ── romanization ──
const INI = ['g', 'kk', 'n', 'd', 'tt', 'r', 'm', 'b', 'pp', 's', 'ss', '', 'j', 'jj', 'ch', 'k', 't', 'p', 'h'];
const MED = ['a', 'ae', 'ya', 'yae', 'eo', 'e', 'yeo', 'ye', 'o', 'wa', 'wae', 'oe', 'yo', 'u', 'wo', 'we', 'wi', 'yu', 'eu', 'ui', 'i'];
// finals as sound classes: k, n, t, l, m, p, ng, '' (and the consonant they carry over before a vowel)
const FIN = ['', 'k', 'k', 'k', 'n', 'n', 'n', 't', 'l', 'k', 'm', 'l', 'l', 'l', 'p', 'l', 'm', 'p', 'p', 't', 't', 'ng', 't', 't', 'k', 't', 'p', 't'];
const CARRY = [null, 'g', 'kk', 'g', 'n', 'n', 'n', 'd', 'r', 'g', 'm', 'r', 'r', 'r', 'p', 'r', 'm', 'b', 'b', 's', 'ss', null, 'j', 'ch', 'k', 't', 'p', null];
function romanize(word) {
  const syl = [...word].map(ch => { const c = ch.charCodeAt(0) - 0xac00; return c >= 0 && c < 11172 ? { i: Math.floor(c / 588), m: Math.floor(c % 588 / 28), f: c % 28 } : { raw: ch }; });
  let out = '';
  for (let k = 0; k < syl.length; k++) {
    const s = syl[k], n = syl[k + 1];
    if (s.raw) { out += s.raw; continue; }
    let ini = s.ini ?? INI[s.i];
    let fin = FIN[s.f];
    if (n && !n.raw && s.f) {
      const ni = n.i;  // next initial: 2 ㄴ, 5 ㄹ, 6 ㅁ, 11 ㅇ
      if (ni === 11 && CARRY[s.f] != null) { n.ini = CARRY[s.f]; fin = ''; }          // liaison: 관악 Gwanak
      else if (ni === 5 && (fin === 'n' || fin === 'l')) { fin = 'l'; n.ini = 'l'; }  // 신림 Sillim, 울릉 Ulleung
      else if (ni === 5 && ['ng', 'm'].includes(fin)) n.ini = 'n';                  // 종로 Jongno
      else if (ni === 5 && fin === 'k') { fin = 'ng'; n.ini = 'n'; }
      else if (ni === 5 && fin === 'p') { fin = 'm'; n.ini = 'n'; }
      else if ((ni === 2 || ni === 6) && fin === 'k') fin = 'ng';                    // 백마 Baengma
      else if ((ni === 2 || ni === 6) && fin === 'p') fin = 'm';
      else if ((ni === 2 || ni === 6) && fin === 't') fin = 'n';
      else if (ni === 2 && fin === 'l') n.ini = 'l';
    }
    out += ini + MED[s.m] + fin;
  }
  return out;
}
const cap = s => s.charAt(0).toUpperCase() + s.slice(1);
const SUFFIX = { 시: 'si', 군: 'gun', 구: 'gu' };
function enName(kname) {  // '수원시' → 'Suwon-si', '중구' → 'Jung-gu'
  const m = /^(.+?)(시|군|구)$/.exec(kname);
  return m ? `${cap(romanize(m[1]))}-${SUFFIX[m[2]]}` : cap(romanize(kname));
}
const SIDO_EN = { '서울특별시': 'Seoul', '부산광역시': 'Busan', '대구광역시': 'Daegu', '인천광역시': 'Incheon', '대전광역시': 'Daejeon', '울산광역시': 'Ulsan',
  '세종특별자치시': 'Sejong', '경기도': 'Gyeonggi-do', '강원특별자치도': 'Gangwon State', '충청북도': 'Chungcheongbuk-do', '충청남도': 'Chungcheongnam-do',
  '전북특별자치도': 'Jeonbuk State', '전남광주통합특별시': 'Jeonnam-Gwangju (integrated)', '경상북도': 'Gyeongsangbuk-do', '경상남도': 'Gyeongsangnam-do', '제주특별자치도': 'Jeju' };

// ── terms (one place, so wording can be changed) ──
const TERM = {
  lv: ['No', 'Provincial/metropolitan ordinance only', 'Yes (own ordinance)'],
  lvPolicy: ['No', 'Yes (provincial/metropolitan)', 'Yes'],
  bikeKind: { 공영: 'public', 민영: 'private', 혼합: 'public + private', '': '' },
  beam: { 직영: 'Directly operated', 프랜차이즈: 'Franchise' },
};
function graceEn(g) {
  if (!g) return '';
  if (/즉시/.test(g)) return 'No grace period';
  return g.replace(/(\d+)\s*분/, '$1 min').replace(/(\d+)\s*시간/, '$1 hr');
}
function noteEn(n) {
  if (!n) return '';
  const known = [
    [/^일반견인구역은 (\d+)분 유예$/, '$1-min grace in regular towing zones'],
    [/^일반견인구역은 (\d+)시간 유예$/, '$1-hr grace in regular towing zones'],
    [/^일반견인구역은 (\d+)시간 유예 \(2026년 개편 전 서구: 서해구·검단구\)$/, '$1-hr grace in regular towing zones (former Seo-gu: now Seohae-gu and Geomdan-gu)'],
    [/^유예시간 미상$/, 'Grace period unknown'],
    [/^견인하지 않음$/, 'Does not tow'],
    [/^최고속도 하향 시범사업과 함께 유예시간을 20분에서 1시간으로 연장\(2026-12-31까지\)$/, 'Grace period extended from 20 min to 1 hr until 31 Dec 2026, together with the speed-limit reduction pilot'],
  ];
  for (const [re, en] of known) if (re.test(n)) return n.replace(re, en);
  return n;  // untranslated note: kept in Korean
}
const GLOSSARY = [
  ['PM (personal mobility)', 'Electric kick scooters and similar devices (개인형 이동장치). "Shared PM" means app-based rental services.'],
  ['Municipality', 'City (-si), county (-gun) or autonomous district (-gu) — the basic local government (기초지자체). Non-autonomous districts inside a city (e.g. Deogyang-gu of Goyang-si) are combined into the city.'],
  ['Province', 'Metropolitan city, special city or province (광역지자체).'],
  ['Not walkable to transit', 'Share of habitable land (forest and water excluded) farther than 500 m in a straight line from any bus stop or rail station.'],
  ['Reachable by PM in 10 min', 'Share of habitable land that is not walkable to transit but within a 10-minute PM ride of a well-served stop or station.'],
  ['Own ordinance / provincial only', 'Whether the municipality has its own ordinance, or is covered only by its province\'s ordinance (provincial rules apply to every municipality in the province).'],
  ['Towing basis', 'The PM ordinance allows the authority to move or tow improperly parked PMs.'],
  ['Towing fee', 'Fee charged to the operator per towed PM (KRW). The municipality\'s own fee, else the province\'s.'],
  ['Grace period', 'Time after a report before a PM is towed. "No grace period" means immediate towing; some of these municipalities still allow a grace period in regular towing zones (see note).'],
  ['Bicycle towing', 'Shared bicycles are towed too; the fee is usually the same as for PMs.'],
  ['Designated parking system', 'PMs may be parked only in designated parking zones (지정주차제).'],
  ['E-scooter Free Zone', 'The municipality runs at least one street or zone where PMs are banned (킥보드 없는 거리); not the whole municipality.'],
  ['Bicycle road types', 'Dedicated bike path (physically separated, 자전거전용도로); shared bike–pedestrian path (겸용도로); bike lane (전용차로); bike-priority road (우선도로).'],
  ['Province/city total', 'Some figures exist only for a whole province or city (e.g. Seoul\'s device count); they are shown as that total, not as the municipality\'s own figure.'],
];

let S, P, C, units = [], beam = {}, sortS = { k: 'pop', asc: false }, sortR = { k: 'sido', asc: true }, shownS = [], shownR = [];

async function main() {
  const [stats, pm, bm] = await Promise.all([fetch(dv('data/stats.json')).then(r => r.json()), fetch(dv('data/pm.json')).then(r => r.ok ? r.json() : {}).catch(() => ({})),
    fetch(dv('data/beam.geojson')).then(r => r.ok ? r.json() : null).catch(() => null)]);
  S = stats; P = pm; C = Object.fromEntries(stats.cols.map((c, i) => [c, i]));
  for (const f of bm?.features || []) beam[f.properties.sgg] = f.properties.kind;
  build();
  const sidos = [...new Map(units.map(u => [u.sido, u.sidonm])).entries()].sort((a, b) => a[0].localeCompare(b[0]));
  for (const [c, n] of sidos) $('sido').add(new Option(`${SIDO_EN[n] || n} (${n})`, c));
  $('sido').onchange = render; $('q').oninput = render;
  $('asof').textContent = `Population ${S.meta.pop_ym.slice(0, 4)}-${S.meta.pop_ym.slice(4)}; shared service status as of end-${(S.meta.pm_ops_date || '').slice(0, 4)}; device and parking figures have different dates per area (shown in the table).`;
  $('glossary').innerHTML = GLOSSARY.map(([t, d]) => `<dt>${esc(t)}</dt><dd>${esc(d)}</dd>`).join('');
  render();
}

// per municipality: members, area figures from the 행정동 rows, and the per-시군구 lookups
function build() {
  const by = new Map();
  for (const r of S.rows) {
    const m = /^(.+시)(.+구)$/.exec(r[C.sggnm]), key = m ? 'c' + r[C.sgg].slice(0, 4) : r[C.sgg];
    const u = by.get(key) || by.set(key, { key, sido: r[C.sido], sidonm: r[C.sidonm], kname: m ? m[1] : r[C.sggnm], sggs: new Set(), rows: [] }).get(key);
    u.sggs.add(r[C.sgg]); u.rows.push(r);
  }
  const habBy = {};
  for (const r of S.rows) habBy[r[C.sgg]] = (habBy[r[C.sgg]] || 0) + r[C.area_km2] * r[C.hab];
  const FLEET = {}, PARK = {}, SURV = {};
  for (const [g, i] of Object.entries(P.fleet_by_sgg || {})) FLEET[g] = P.fleet[i];
  for (const u of P.parking_units || []) for (const g of u.sgg) PARK[g] = u;
  for (const u of P.survey || []) for (const g of u.sgg) (SURV[g] ??= []).push(u);
  const unitsOf = (map, mem) => { const us = [...new Set(mem.map(g => map[g]).filter(Boolean))]; return us.length ? { us, wide: us.some(u => u.sgg.some(g => !mem.includes(g))), partial: mem.some(g => !map[g]) } : null; };
  const short = n => { const t = String(n).split(' ').pop(); return SIDO_EN[t] || enName(t); };
  // shared PM service from the end-2024 survey; a newer device count above zero for the municipality itself wins
  const OPSNEW = {};
  for (const [g, u] of Object.entries(FLEET)) {
    const d = String(u.date || '').split(' · ').sort().pop();
    if (S.sgg_pm_ops?.[g] === 0 && u.total > 0 && new Set(u.sgg.map(q => q.slice(0, 4))).size === 1 && d > (S.meta.pm_ops_date || '')) OPSNEW[g] = d;
  }
  units = [...by.values()].map(u => {
    const mem = [...u.sggs], g = mem[0];
    let pop = 0, hab = 0, e = 0, eA = 0, pmv = 0, pA = 0;
    for (const r of u.rows) {
      const a = r[C.area_km2] * r[C.hab];
      pop += r[C.pop] || 0; hab += a;
      if (r[C.h_either] != null) { e += a * r[C.h_either]; eA += a; }
      if (r[C.h_walk] != null) { pmv += a * (r[C.h_pm5] + r[C.h_pm10]); pA += a; }
    }
    const fl = unitsOf(FLEET, mem), pk = unitsOf(PARK, mem);
    const flTot = fl && !fl.wide ? fl.us.reduce((a, x) => a + x.total, 0) : null, flPop = fl ? (fl.wide ? fl.us[0].pop : fl.us.reduce((a, x) => a + (x.pop || 0), 0)) : 0;
    const pkN = pk && !pk.wide ? pk.us.reduce((a, x) => a + x.n, 0) : null;
    const pkArea = pk ? (pk.wide ? pk.us[0].sgg : pk.us.flatMap(x => x.sgg)).reduce((a, q) => a + (habBy[q] || 0), 0) : 0;
    const sv = (SURV[g] || []).filter(x => x.bike_pub != null || x.bike_pri != null).sort((a, b) => a.sgg.length - b.sgg.length)[0];
    const bk = mem.map(q => S.sgg_bike_road?.[q]).filter(Boolean), bkAll = bk.length ? bk.flat().reduce((a, b) => a + b, 0) : null, bkDed = bk.length ? bk.reduce((a, v) => a + v[0], 0) : null;
    const o = S.sgg_ordinance?.[g], bikeOps = S.sgg_bike_ops?.[g];
    return { ...u, mem, rep: g, name: enName(u.kname), pop, hab,
      either: eA ? 1 - e / eA : null, pm: pA ? pmv / pA : null,  // h_either: share within walking distance
      pmops: OPSNEW[g] ? 1 : S.sgg_pm_ops?.[g] ?? null, opsNew: OPSNEW[g] || '', bikeops: bikeOps ? bikeOps[0] : null, bikekind: bikeOps ? TERM.bikeKind[bikeOps[1]] ?? bikeOps[1] : '',
      fleet: flTot, fleetWide: fl?.wide ? `${short(fl.us[0].name)} total ${num(fl.us[0].total)}` : '', fleetPart: !!fl?.partial && !fl.wide,
      fleetDate: fl ? [...new Set(fl.us.map(x => x.date))].join(' · ') : '', fleetPc: fl && flPop ? (fl.wide ? fl.us[0].total : flTot) / flPop * 1000 : null, fleetPcAvg: !!fl?.wide,
      bikes: sv && !sv.sgg.some(q => !mem.includes(q)) ? (sv.bike_pub || 0) + (sv.bike_pri || 0) : null,
      bikesWide: sv && sv.sgg.some(q => !mem.includes(q)) ? `${short(sv.name)} total ${num((sv.bike_pub || 0) + (sv.bike_pri || 0))}` : '',
      park: pkN, parkWide: pk?.wide ? `${short(pk.us[0].name)} total ${num(pk.us[0].n)}` : '', parkPart: !!pk?.partial && !pk.wide,
      parkD: pk && pkArea ? (pk.wide ? pk.us[0].n : pkN) / pkArea : null, parkDate: pk ? [...new Set(pk.us.map(x => x.date))].join(' · ') : '',
      bkAll, bkDed, beam: TERM.beam[beam[g]] || '',
      o, ordO: o ? o.lv?.o ?? (o.o ? 2 : 0) : null, ordM: o ? o.lv?.m ?? (o.m ? 2 : 0) : null, tow: o ? o.t : null, towLv: o?.lv?.t ?? null,
      fee: o?.t ? o.fee : null, planned: !!o?.planned, grace: o?.t ? graceEn(o.grace) : '', graceMin: o?.t && o.grace ? (/즉시/.test(o.grace) ? 0 : +((/(\d+)\s*분/.exec(o.grace) || [])[1] || ((/(\d+)\s*시간/.exec(o.grace) || [])[1] || 0) * 60)) : null,
      note: o ? noteEn(o.note) : '', btow: o ? o.b : null, btowLv: o?.lv?.b ?? null, dpark: o?.lv?.p ?? null, nokick: o?.lv?.n ?? null,
      source: o?.practice ? 'Towing practice table' + (/구미/.test(o.practice) ? ' (Gumi, Nov 2026)' : ' (Nov 2026)') : o ? 'Ordinance analysis' : '' };
  });
}

const STATUS = [
  { k: 'sidoEn', h: 'Province', l: 1, f: (v, u) => esc(SIDO_EN[u.sidonm] || u.sidonm) },
  { k: 'name', h: 'Municipality', l: 1, f: (v, u) => `${esc(v)} <small>${esc(u.kname)}</small>` },
  { k: 'pop', h: 'Population', f: v => num(v) },
  { k: 'either', h: 'Not walkable to transit (% habitable land)', f: pct },
  { k: 'pm', h: 'Reachable by PM in 10 min (% habitable land)', f: pct },
  { k: 'pmops', h: 'Shared PM service', f: (v, u) => v == null ? '' : v ? 'Yes' + (u.opsNew ? ` <small>(device data ${esc(u.opsNew)}; none in the end-2024 survey)</small>` : '') : 'No' },
  { k: 'fleet', h: 'Shared PM devices', f: (v, u) => v != null ? num(v) + (u.fleetPart ? ' <small>(some districts only)</small>' : '') + ` <small>${esc(u.fleetDate)}</small>` : u.fleetWide ? `<small>${esc(u.fleetWide)}</small>` : '' },
  { k: 'fleetPc', h: 'Devices per 1,000 residents', f: (v, u) => v == null ? '' : num(v, 1) + (u.fleetPcAvg ? ' <small>(area avg.)</small>' : '') },
  { k: 'bikeops', h: 'Shared bike service', f: (v, u) => v == null ? '' : v ? 'Yes' + (u.bikekind ? ` (${esc(u.bikekind)})` : '') : 'No' },
  { k: 'bikes', h: 'Shared bikes (end-2024)', f: (v, u) => v != null ? num(v) : u.bikesWide ? `<small>${esc(u.bikesWide)}</small>` : '' },
  { k: 'park', h: 'PM parking zones', f: (v, u) => v != null ? num(v) + (u.parkPart ? ' <small>(some districts only)</small>' : '') + ` <small>${esc(u.parkDate)}</small>` : u.parkWide ? `<small>${esc(u.parkWide)}</small>` : '' },
  { k: 'parkD', h: 'Parking zones per km² (habitable)', f: v => v == null ? '' : num(v, 1) },
  { k: 'bkAll', h: 'Bicycle roads (km)', f: v => v == null ? '' : num(v, 1) },
  { k: 'bkDed', h: 'Dedicated bike paths (km)', f: v => v == null ? '' : num(v, 1) },
  { k: 'beam', h: 'Beam operation', l: 1, f: esc },
];
const REG = [
  STATUS[0], STATUS[1],
  { k: 'ordO', h: 'PM ordinance', l: 1, f: v => v == null ? '' : TERM.lv[v] },
  { k: 'ordM', h: 'Towing basis in ordinance', l: 1, f: v => v == null ? '' : TERM.lv[v] },
  { k: 'tow', h: 'PM towing', l: 1, f: (v, u) => v == null ? '' : v ? 'Yes' + (u.towLv === 1 ? ' <small>(provincial/metropolitan)</small>' : '') : 'No' },
  { k: 'fee', h: 'Towing fee (KRW)', f: (v, u) => v == null ? '' : num(v) + (u.planned ? ' <small>(planned)</small>' : '') },
  { k: 'graceMin', h: 'Grace period', l: 1, f: (v, u) => esc(u.grace) + (u.note && u.tow ? ` <small>${esc(u.note)}</small>` : '') },
  { k: 'btow', h: 'Bicycle towing', l: 1, f: (v, u) => v == null ? '' : v ? 'Yes' + (u.tow && u.fee ? ' <small>(same fee as PM)</small>' : '') + (u.btowLv === 1 ? ' <small>(provincial ordinance)</small>' : '') : 'No' },
  { k: 'dpark', h: 'Designated parking system', l: 1, f: v => v == null ? '' : TERM.lvPolicy[v] },
  { k: 'nokick', h: 'E-scooter Free Zone', l: 1, f: v => v == null ? '' : TERM.lvPolicy[v] },
  { k: 'source', h: 'Towing source', l: 1, f: (v, u) => esc(v) + (!u.tow && u.note ? ` <small>${esc(u.note)}</small>` : '') },
];

function filtered() {
  const sido = $('sido').value, q = $('q').value.trim().toLowerCase();
  return units.filter(u => (!sido || u.sido === sido) && (!q || u.name.toLowerCase().includes(q) || u.kname.includes(q) || (SIDO_EN[u.sidonm] || '').toLowerCase().includes(q) || u.sidonm.includes(q)));
}
function table(el, cols, data, sort, onSort) {
  const val = (u, k) => k === 'sidoEn' ? u.sido + u.name : u[k];
  const rows = [...data].sort((a, b) => { const p = val(a, sort.k), q = val(b, sort.k); return (p == null || p === '') - (q == null || q === '') || (typeof p === 'string' ? p.localeCompare(q) : p - q) * (sort.asc ? 1 : -1); });
  el.innerHTML = '<thead><tr>' + cols.map(c => `<th data-k="${c.k}" class="${c.l ? 'l ' : ''}${sort.k === c.k ? 'on' + (sort.asc ? ' asc' : '') : ''}">${c.h}</th>`).join('') + '</tr></thead><tbody>' +
    rows.map(u => '<tr>' + cols.map(c => `<td class="${c.l ? 'l' : ''}">${c.f(u[c.k], u)}</td>`).join('') + '</tr>').join('') + '</tbody>';
  el.querySelectorAll('th').forEach(th => th.onclick = () => onSort(th.dataset.k));
  return rows;
}
function render() {
  const data = filtered();
  shownS = table($('t-status'), STATUS, data, sortS, k => { sortS = { k, asc: sortS.k === k ? !sortS.asc : ['sidoEn', 'name', 'beam'].includes(k) }; render(); });
  shownR = table($('t-reg'), REG, data, sortR, k => { sortR = { k, asc: sortR.k === k ? !sortR.asc : ['sidoEn', 'name', 'graceMin'].includes(k) }; render(); });
  const sum = (k, f = u => u[k]) => data.reduce((a, u) => a + (f(u) || 0), 0);
  $('note-status').textContent = `${data.length} municipalities · population ${num(sum('pop'))} · shared PM service in ${data.filter(u => u.pmops === 1).length}, none in ${data.filter(u => u.pmops === 0).length} · Beam operates in ${data.filter(u => u.beam).length}. Blank = no data (not zero). Grey "… total" = figure exists only for the whole province or city.`;
  const tows = data.filter(u => u.tow), fees = tows.map(u => u.fee).filter(Boolean).sort((a, b) => a - b);
  $('note-reg').textContent = `${tows.length} of ${data.length} municipalities tow PMs` + (fees.length ? ` (fee KRW ${num(fees[0])}–${num(fees[fees.length - 1])}, median ${num(fees[Math.floor(fees.length / 2)])})` : '') +
    ` · designated parking system in ${data.filter(u => u.dpark).length} · E-scooter Free Zones in ${data.filter(u => u.nokick).length}. Where a towing practice table exists it overrides the ordinance for towing, fee and grace period.`;
}
function csv(name, cols, rows) {
  const strip = s => String(s ?? '').replace(/<[^>]+>/g, '').replace(/\s+/g, ' ').trim();
  const q = v => /[",\n]/.test(v) ? `"${v.replace(/"/g, '""')}"` : v;
  const lines = [['Korean name', ...cols.map(c => c.h)].map(q).join(','), ...rows.map(u => [u.sidonm + ' ' + u.kname, ...cols.map(c => strip(c.f(u[c.k], u)))].map(q).join(','))];
  const a = Object.assign(document.createElement('a'), { href: URL.createObjectURL(new Blob(['﻿' + lines.join('\n')], { type: 'text/csv' })), download: name });
  a.click(); URL.revokeObjectURL(a.href);
}
$('csv-status').onclick = () => csv('korea_pm_status_by_municipality.csv', STATUS, shownS);
$('csv-reg').onclick = () => csv('korea_pm_regulation_by_municipality.csv', REG, shownR);
main().catch(e => { $('note-status').textContent = 'Could not load the data: ' + e.message; console.error(e); });
