"""Build site/data from raw/ (see fetch.py for the sources).

1. Bus stops: the 국토교통부 file, plus OpenStreetMap stops in 시군구 the file barely covers (fewer than OSM_FILL of
   the OSM count there); an OSM stop within DEDUP_M of a 국토부 stop is the same stop.
2. Route counts (정차 노선수) are attached to stops by name within the same 시군구 (the API has names and 법정동 codes
   but no coordinates): by 시군구 code, else by 시군구 name (the API keeps pre-2026 codes, so its 시도 are mapped onto
   the current ones, SIDO_GROUP), else (인천's new 구) by a name unique within the 시도. A 시군구 whose stops match less than
   ROUTE_MATCH_MIN gets no route figures. A non-dense 시군구 with fewer than GAP_STOPS_PER_1000 stops per 1,000 people
   lacks stop data in both sources (e.g. 화천, 속초) and gets no bus figures instead of a false gap.
3. Coverage per 행정동 on a Web Mercator pixel grid (~170 m): the share of its area within BUS_M of a bus stop, within
   RAIL_M of a railway station, and within BUS_M of a stop served by GOOD_ROUTES or more routes; and the PM classes of
   GRID_CLASSES (도보권, PM 5분권, PM 10분권, beyond) around PM anchors (stations, well-served stops, and every stop where
   route counts are unknown), drawn as pmgrid.png. Distances are straight lines.
3b. PM 잠재 지수 per 행정동: mean percentile rank of the PM-reachable share, population density, 상가 density and (once
    the 행정동 age data is there) the share of residents aged 20–39.
3c. 산업단지 (한국산업단지공단), LH 임대 세대 and age structure (20–39, 70+) per 시군구.
4. 행정동 type from the name: 동 (urban 행정구역), 읍, 면.
5. Monthly 교통카드 trips per 시군구 (교통수단별 이용량, 환승 이용량), as a daily average of 출발·승차 통행.
6. 법정 도시지역 (국토계획법 용도지역) area and population shares per 시군구 from the 도시계획현황 statistics.

Outputs (site/data): dongs.geojson (simplified boundaries), stats.json (one row per 행정동 + metadata), stops.json,
stations.json, pmgrid.png, download/dongs.csv.
"""
import calendar
import csv
import glob
import json
import math
import os
import re
from collections import defaultdict

import numpy as np
import shapely
from PIL import Image
from scipy.spatial import cKDTree

RAW = os.path.join(os.path.dirname(__file__), "..", "raw")
OUT = os.path.join(os.path.dirname(__file__), "..", "site", "data")
BUS_M, RAIL_M = 500, 1000
GOOD_ROUTES = 3  # a stop with fewer routes counts as sparsely served
OSM_FILL, DEDUP_M = 0.5, 50
ROUTE_MATCH_MIN = 0.6
GAP_STOPS_PER_1000, GAP_DENSITY = 2.0, 3000  # a non-dense 시군구 (people per ㎢) with fewer stops per 1,000 people lacks stop data
SIDO_GROUP = {"29": "12", "46": "12", "42": "51", "45": "52"}  # 광주·전남 → 전남광주통합특별시, old 강원·전북 codes
SIMPLIFY_DEG = 0.0004  # ~40 m
# PM first/last mile (Geurs & van Wee's contour measure): reach within 5 and 10 minutes of riding, as straight lines
PM_SPEED_KMH, PM_DETOUR = 15, 1.3  # assumed average riding speed and road distance / straight distance
PM5_M, PM10_M = (round(PM_SPEED_KMH * 1000 / 60 * m / PM_DETOUR) for m in (5, 10))
# Web Mercator pixel grid over South Korea (under 4096 px a side, the usual WebGL texture limit); ~170 m at 36°N
LON0, LON1, LAT0, LAT1, PIX_M, R_EARTH = 124.5, 132.0, 33.0, 38.7, 210, 6378137.0
GRID_CLASSES = {1: ("도보권", None), 2: ("PM 5분권", (235, 104, 52, 210)), 3: ("PM 10분권", (246, 179, 143, 190)),
                4: ("PM으로도 먼 곳", (82, 81, 78, 130)), 5: ("정류장 자료 부족", (214, 213, 208, 170))}  # 0: outside Korea


def load(name):
    with open(os.path.join(RAW, name), encoding="utf-8") as f:
        return json.load(f)


def proj(lon, lat):
    """Metres on a local equirectangular projection (straight-line distances within a few km are off by well under 1%)."""
    lon, lat = np.asarray(lon, float), np.asarray(lat, float)
    return np.column_stack([(lon - 127.5) * 111320 * np.cos(np.radians(lat)), lat * 110574])


def norm(name):
    return re.sub(r"[\s.\-·,()（）]", "", name or "")


def dong_type(name):
    return {"동": "동", "읍": "읍", "면": "면"}.get(name[-1:], "동")


def assign(tree, lon, lat):
    """Index of the 행정동 containing each point, -1 outside every 행정동."""
    out = np.full(len(lon), -1)
    if len(lon):
        pi, di = tree.query(shapely.points(lon, lat), predicate="within")
        out[pi] = di
    return out


def load_routes():
    """{시군구 code: {name: routes}}, {(sido group, 시군구 name): {name: routes}} and {sido group: {name: {routes, …}}}
    from the newest day of each 시군구."""
    latest = {}
    for path in sorted(glob.glob(os.path.join(RAW, "routes", "*", "*_*.json"))):
        latest[os.path.basename(path)] = path  # sorted by day, so later days win
    by_code, by_sgg, by_sido, days = defaultdict(dict), defaultdict(dict), defaultdict(lambda: defaultdict(set)), set()
    for path in latest.values():
        ctpv, sgg = os.path.basename(path)[:-5].split("_")
        g = SIDO_GROUP.get(ctpv, ctpv)
        d = load(os.path.relpath(path, RAW))
        days.add(os.path.basename(os.path.dirname(path)))
        for sid, name, _emd, n in d["stops"]:
            if not name or "[" in name:  # subway stations appear as "역명 [노선]"
                continue
            k = norm(name)
            for m in (by_code[sgg], by_sgg[(g, norm(d["sgg_nm"]))]):
                m[k] = max(m.get(k, 0), n)
            by_sido[g][k].add(n)
    return by_code, by_sgg, by_sido, sorted(days), len(latest)


def load_trips(dongs):
    """Monthly trips per current 시군구 code: {sgg: {"modes": {...}, "transfer": {...}}} from the newest month of each
    file, plus the months used. API codes map by code, else by (시도 group, 시군구 name); 인천's pre-2026 중구·동구·서구
    match no current 구 and are left out."""
    names = {(d["sido"], norm(d["sggnm"])): d["sgg"] for d in dongs}
    codes = {d["sgg"] for d in dongs}
    latest = {}
    for path in sorted(glob.glob(os.path.join(RAW, "trips", "*", "*_*_*.json"))):
        latest[os.path.basename(path)] = path
    out, months, lost = defaultdict(dict), set(), set()
    for base, path in latest.items():
        kind, ctpv, sgg = base[:-5].split("_")
        d = load(os.path.relpath(path, RAW))
        g = sgg if sgg in codes else names.get((SIDO_GROUP.get(ctpv, ctpv), norm(d["sgg_nm"])))
        if not g:
            lost.add(f"{ctpv}_{sgg} {d['sgg_nm']}")
            continue
        ym = os.path.basename(os.path.dirname(path))
        months.add(ym)
        days = calendar.monthrange(int(ym[:4]), int(ym[4:]))[1]
        prev = out[g].get(kind)
        cur = {"day": d["ocrn"] / days, "by_mode": {m: v[0] / days for m, v in d["by_mode"].items()},
               "by_user": {u: v / days for u, v in d["by_user"].items()}}
        if prev:  # several old codes became one 시군구 (광주·전남 keep theirs, so this is rare)
            cur["day"] += prev["day"]
            for k in ("by_mode", "by_user"):
                for m, v in prev[k].items():
                    cur[k][m] = cur[k].get(m, 0) + v
        out[g][kind] = cur
    return out, sorted(months), sorted(lost)


UPIS_SIDO = {"서울특별시": "11", "부산광역시": "26", "대구광역시": "27", "인천광역시": "28", "광주광역시": "12", "전라남도": "12",
             "대전광역시": "30", "울산광역시": "31", "세종특별자치시": "36", "경기도": "41", "강원특별자치도": "51", "충청북도": "43",
             "충청남도": "44", "전북특별자치도": "52", "경상북도": "47", "경상남도": "48", "제주특별자치도": "50"}


def merc_x(lon):
    return R_EARTH * np.radians(lon)


def merc_y(lat):
    return R_EARTH * np.log(np.tan(np.pi / 4 + np.radians(lat) / 2))


def inv_merc_y(y):
    return np.degrees(2 * np.arctan(np.exp(np.asarray(y) / R_EARTH)) - np.pi / 2)


def write_grid(img, w, h):
    """The PM grid as a palette PNG (pmgrid.png); 도보권 and outside are transparent."""
    pal, alpha = [], []
    for k in range(6):
        rgba = GRID_CLASSES.get(k, (None, None))[1] or (0, 0, 0, 0)
        pal += rgba[:3]
        alpha.append(rgba[3])
    im = Image.fromarray(img, "P")
    im.putpalette(pal + [0] * (768 - len(pal)))
    im.save(os.path.join(OUT, "pmgrid.png"), transparency=bytes(alpha), optimize=True)
    print(f"pm grid: {w} x {h} px, " + ", ".join(f"{GRID_CLASSES[k][0]} {np.sum(img == k):,}" for k in GRID_CLASSES), flush=True)


def load_stores(tree, dongs):
    """상가업소 count per 행정동 from raw/stores/<sgg>.json, the 시군구 that have a file, and the newest base month."""
    n = np.zeros(len(dongs))
    ok, yms = set(), set()
    for path in glob.glob(os.path.join(RAW, "stores", "*.json")):
        d = load(os.path.relpath(path, RAW))
        ok.add(os.path.basename(path)[:-5])
        yms.add(d.get("ym") or "")
        if d["stores"]:
            xy = np.array([s[:2] for s in d["stores"]])
            di = assign(tree, xy[:, 0], xy[:, 1])
            np.add.at(n, di[di >= 0], 1)
    return n, ok, max(yms - {""}, default=None)


IND_SIDO = {"서울": "11", "부산": "26", "대구": "27", "인천": "28", "광주": "12", "전남": "12", "대전": "30", "울산": "31", "세종": "36",
            "경기": "41", "강원": "51", "충북": "43", "충남": "44", "전북": "52", "경북": "47", "경남": "48", "제주": "50"}


def load_industrial(dongs):
    """산업단지 per current 시군구 from scripts/static/industrial.csv (한국산업단지공단, see industrial_csv.py):
    {sgg: {n, firms, area (천㎡), old, date, city}}. Complexes listed for a whole 시 that has 구 count for every 구 of
    that 시 (city = the 시); 인천's pre-2026 중구·서구 match no current 구."""
    path = os.path.join(os.path.dirname(__file__), "static", "industrial.csv")
    if not os.path.exists(path):
        return {}, []
    with open(path, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    sggs = {(d["sido"], d["sgg"], norm(d["sggnm"])) for d in dongs}
    out, lost = {}, set()
    for r in rows:
        sido, name = IND_SIDO.get(r["시도"]), norm(r["시군구"])
        exact = [g for s, g, n in sggs if s == sido and (n == name or (sido == "36" and r["시도"] == "세종"))]
        city = [g for s, g, n in sggs if s == sido and name.endswith("시") and n.startswith(name)] if not exact else []
        if not exact and not city:
            lost.add(f"{r['시도']} {r['시군구']}")
            continue
        for g in exact or city:
            v = out.setdefault(g, {"n": 0, "firms": 0, "area": 0.0, "old": 0, "date": r["기준일"], "city": None})
            v["n"] += 1
            v["firms"] += int(float(r["가동업체"] or 0))
            v["area"] += float(r["관리면적_천m2"] or 0)
            v["old"] += int(r["노후"])
            if city:
                v["city"] = r["시군구"]
    return out, sorted(lost)


def load_age(dongs):
    """Age structure per current 시군구 from raw/age.json: {sgg: {y2039, o70}} (shares of 20–39 and 70+), and the month.
    By code, else by (시도 group, 시군구 name); a 시 row whose 구 are listed too is ignored by the code match."""
    if not os.path.exists(os.path.join(RAW, "age.json")):
        return {}, None
    d = load("age.json")
    codes = {x["sgg"] for x in dongs}
    names = {(x["sido"], norm(x["sggnm"])): x["sgg"] for x in dongs}
    out = {}
    for r in d["rows"]:
        c = r["code"][:5]
        g = c if c in codes else names.get((SIDO_GROUP.get(c[:2], c[:2]), norm(r["sgg"])))
        if g and r["tot"] and g not in out:
            a = r["ages"]
            out[g] = {"y2039": round((a["20"] + a["30"]) / r["tot"], 4), "o70": round(sum(a[str(k)] for k in (70, 80, 90, 100)) / r["tot"], 4)}
    return out, d["ym"]


def lh_table():
    return load("lh.json")["table"] if os.path.exists(os.path.join(RAW, "lh.json")) else None


def load_lh(dongs):
    """LH 임대 세대 per current 시군구, from the 단지 whose 주소 names a 시군구: ({sgg: {units, complexes}}, 단지, with address)."""
    if not os.path.exists(os.path.join(RAW, "lh.json")):
        return {}, 0, 0
    rows = load("lh.json")["rows"]
    names = defaultdict(list)
    for d in dongs:
        names[norm(d["sggnm"])].append((d["sidonm"], d["sgg"]))
    out, addr = {}, 0
    for name, units, rent, _kind, address in rows:
        parts = (address or "").split()
        if len(parts) < 2:
            continue
        addr += 1
        cand = [norm(parts[1] + parts[2])] if len(parts) > 2 and parts[2].endswith("구") and parts[1].endswith("시") else []
        cand.append(norm(parts[1]))
        g = next((sg for c in cand for sd, sg in names.get(c, []) if sd[:2] == parts[0][:2] or len(names[c]) == 1), None)
        if g and "임대" in (rent or "") and units:
            v = out.setdefault(g, {"units": 0, "complexes": 0})
            v["units"] += int(units)
            v["complexes"] += 1
    return out, len(rows), addr


def load_upis(dongs):
    """도시지역 per current 시군구 code from scripts/static/upis.csv (국토교통부 도시계획현황, see upis_csv.py):
    {sgg: {area, pop, res, com, ind, green, city}}. The statistics list a 시 with 구 once, so its 구 share the 시's values
    (city = that 시's name); 인천's pre-2026 중구·동구·서구 match no current 구."""
    path = os.path.join(os.path.dirname(__file__), "static", "upis.csv")
    if not os.path.exists(path):
        return {}, None
    with open(path, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    by_sido = defaultdict(list)
    for r in rows:
        by_sido[UPIS_SIDO.get(r["시도"])].append(r)
    out = {}
    for sido, sgg, name in {(d["sido"], d["sgg"], d["sggnm"]) for d in dongs}:
        cands = by_sido.get(sido, [])
        r = next((c for c in cands if c["시군구"] == name), None) \
            or next((c for c in cands if c["시군구"].endswith("시") and name.startswith(c["시군구"])), None) \
            or (cands[0] if len(cands) == 1 else None)
        if not r:
            continue
        total, urban = float(r["용도지역합계_m2"]), float(r["도시지역_m2"])
        share = lambda k: round(float(r[k]) / urban, 4) if urban else None
        out[sgg] = {"area": round(urban / total, 4) if total else None,
                    "pop": round(float(r["도시지역인구"]) / float(r["전체인구"]), 4) if r["전체인구"] and float(r["전체인구"]) else None,
                    "res": share("주거_m2"), "com": share("상업_m2"), "ind": share("공업_m2"), "green": share("녹지_m2"),
                    "city": r["시군구"] if r["시군구"] != name else None}
    return out, rows[0]["기준연도"] if rows else None


def main():
    os.makedirs(os.path.join(OUT, "download"), exist_ok=True)
    adm = load("admin_dong.json")
    dongs = adm["dongs"]
    geoms = [shapely.MultiPolygon([(p[0], p[1:]) for p in d["polys"]]).buffer(0) for d in dongs]
    tree = shapely.STRtree(geoms)
    pgeoms = [shapely.transform(g, lambda xy: proj(xy[:, 0], xy[:, 1])) for g in geoms]
    area = np.array([g.area for g in pgeoms])
    pop_raw = load("dong_pop.json")
    pop = [pop_raw["pop"].get(d["code"]) for d in dongs]
    print(f"dongs: {len(dongs)} ({adm['ver']}), population matched {sum(p is not None for p in pop)}, "
          f"{sum(p or 0 for p in pop):,} people (주민등록 {pop_raw['ym']}: {sum(pop_raw['pop'].values()):,})", flush=True)

    # 1. stops
    sm = load("stops_molit.json")
    m_lon = np.array([s[3] for s in sm["stops"]]); m_lat = np.array([s[2] for s in sm["stops"]])
    m_dong = assign(tree, m_lon, m_lat)
    osm = load("stops_osm.json")
    o_lon = np.array([s[3] for s in osm]); o_lat = np.array([s[2] for s in osm])
    o_dong = assign(tree, o_lon, o_lat)
    sgg_of = np.array([d["sgg"] for d in dongs])
    m_cnt = defaultdict(int); o_cnt = defaultdict(int)
    for i in m_dong[m_dong >= 0]:
        m_cnt[sgg_of[i]] += 1
    for i in o_dong[o_dong >= 0]:
        o_cnt[sgg_of[i]] += 1
    fill = {g for g in set(sgg_of) if m_cnt[g] < OSM_FILL * o_cnt[g]}
    near, _ = cKDTree(proj(m_lon, m_lat)).query(proj(o_lon, o_lat))
    add = (o_dong >= 0) & np.isin(sgg_of[np.maximum(o_dong, 0)], list(fill)) & (near > DEDUP_M)
    keep = m_dong >= 0
    s_lon = np.concatenate([m_lon[keep], o_lon[add]]); s_lat = np.concatenate([m_lat[keep], o_lat[add]])
    s_dong = np.concatenate([m_dong[keep], o_dong[add]])
    s_name = [s[1] for s, k in zip(sm["stops"], keep) if k] + [s[1] for s, a in zip(osm, add) if a]
    s_src = np.concatenate([np.zeros(keep.sum(), int), np.ones(add.sum(), int)])
    print(f"stops: 국토부 {len(m_lon)} ({keep.sum()} inside a 행정동, collected {sm['collected']}), OSM {len(o_lon)}; "
          f"{len(fill)} 시군구 filled from OSM (+{add.sum()} stops): "
          + ", ".join(sorted(f"{dongs[np.where(sgg_of == g)[0][0]]['sggnm']}({m_cnt[g]}/{o_cnt[g]})" for g in fill)), flush=True)

    # 2. route counts
    by_code, by_sgg, by_sido, rdays, nfiles = load_routes()
    s_rte = np.full(len(s_lon), -1)
    for j in range(len(s_lon)):
        d = dongs[s_dong[j]]
        k = norm(s_name[j])
        n = by_code.get(d["sgg"], {}).get(k)
        if n is None:
            n = by_sgg.get((d["sido"], norm(d["sggnm"])), {}).get(k)
        if n is None:
            vals = by_sido.get(d["sido"], {}).get(k)
            n = next(iter(vals)) if vals and len(vals) == 1 else None
        if n is not None:
            s_rte[j] = n
    tot, hit = defaultdict(int), defaultdict(int)
    for j in range(len(s_lon)):
        g = sgg_of[s_dong[j]]
        tot[g] += 1
        hit[g] += s_rte[j] >= 0
    route_ok = {g for g in tot if hit[g] >= ROUTE_MATCH_MIN * tot[g]}
    s_rte_ok = np.array([s_rte[j] if sgg_of[s_dong[j]] in route_ok else -1 for j in range(len(s_lon))])
    print(f"routes: {nfiles} 시군구 files (days {', '.join(rdays) or '-'}); matched {np.sum(s_rte >= 0)} of {len(s_lon)} stops; "
          f"{len(route_ok)} of {len(tot)} 시군구 with route figures (match ≥ {ROUTE_MATCH_MIN:.0%})", flush=True)
    low = sorted(((hit[g] / tot[g], g) for g in tot if g not in route_ok))
    print("  without route figures: " + ", ".join(f"{dongs[np.where(sgg_of == g)[0][0]]['sggnm']} {r:.0%}" for r, g in low), flush=True)

    # stations
    st = load("stations_osm.json")
    t_lon = np.array([s[2] for s in st]); t_lat = np.array([s[1] for s in st])
    t_dong = assign(tree, t_lon, t_lat)
    seen, stations = [], []
    for s, d, lo, la in zip(st, t_dong, t_lon, t_lat):
        if d < 0:
            continue
        p = proj([lo], [la])[0]
        if any(n == s[0] and abs(p[0] - q[0]) < 500 and abs(p[1] - q[1]) < 500 for n, q in seen):
            continue  # the same station mapped as a node and as an area
        seen.append((s[0], p))
        stations.append([round(lo, 5), round(la, 5), s[0]])
    print(f"stations: {len(st)} from OSM, {len(stations)} inside Korea after removing duplicates", flush=True)

    # 시군구 whose stops are missing from both sources: no bus figures rather than a false gap
    g_stop, g_pop, g_area = defaultdict(int), defaultdict(float), defaultdict(float)
    for j in range(len(s_lon)):
        g_stop[sgg_of[s_dong[j]]] += 1
    for i, d in enumerate(dongs):
        g_pop[d["sgg"]] += pop[i] or 0
        g_area[d["sgg"]] += area[i] / 1e6
    stop_gap = {g for g in g_pop if g_pop[g] and g_stop[g] / g_pop[g] * 1000 < GAP_STOPS_PER_1000 and g_pop[g] / g_area[g] < GAP_DENSITY}
    print("stop data gaps (no bus figures): " + ", ".join(sorted(f"{dongs[np.where(sgg_of == g)[0][0]]['sggnm']}({g_stop[g]})" for g in stop_gap)), flush=True)

    # 3. coverage on a Web Mercator pixel grid, which is also the PM grid image
    rail_xy = proj([s[0] for s in stations], [s[1] for s in stations])
    bus_t, rail_t = cKDTree(proj(s_lon, s_lat)), cKDTree(rail_xy)
    good = s_rte_ok >= GOOD_ROUTES
    good_t = cKDTree(proj(s_lon[good], s_lat[good])) if good.any() else None
    # PM anchors: stations, stops with GOOD_ROUTES+ routes, and every stop where route counts are unknown
    anchor = good | ~np.isin(sgg_of[s_dong], list(route_ok))
    anchor_t = cKDTree(proj(s_lon[anchor], s_lat[anchor]))
    W, H = math.ceil((merc_x(LON1) - merc_x(LON0)) / PIX_M), math.ceil((merc_y(LAT1) - merc_y(LAT0)) / PIX_M)
    img = np.zeros((H, W), np.uint8)  # GRID_CLASSES
    cov = np.zeros((len(dongs), 8))  # bus, rail, either, well-served bus, walk, PM 5 min, PM 10 min, beyond
    for i, g in enumerate(geoms):
        lo0, la0, lo1, la1 = g.bounds
        c = np.arange(max(0, int((merc_x(lo0) - merc_x(LON0)) / PIX_M)), min(W, int((merc_x(lo1) - merc_x(LON0)) / PIX_M) + 1))
        r = np.arange(max(0, int((merc_y(LAT1) - merc_y(la1)) / PIX_M)), min(H, int((merc_y(LAT1) - merc_y(la0)) / PIX_M) + 1))
        C_, R_ = np.meshgrid(c, r)
        lon = LON0 + np.degrees((C_.ravel() + 0.5) * PIX_M / R_EARTH)
        lat = inv_merc_y(merc_y(LAT1) - (R_.ravel() + 0.5) * PIX_M)
        inside = shapely.contains_xy(g, lon, lat)
        if inside.any():
            pts, rr, cc = proj(lon[inside], lat[inside]), R_.ravel()[inside], C_.ravel()[inside]
        else:  # smaller than a pixel
            p = g.representative_point()
            pts, rr, cc = proj([p.x], [p.y]), None, None
        b = bus_t.query(pts, distance_upper_bound=BUS_M)[0] <= BUS_M
        dr = rail_t.query(pts, distance_upper_bound=PM10_M)[0]
        w = good_t.query(pts, distance_upper_bound=BUS_M)[0] <= BUS_M if good_t else np.zeros(len(pts), bool)
        da = anchor_t.query(pts, distance_upper_bound=PM10_M)[0]
        walk = (da <= BUS_M) | (dr <= RAIL_M)
        near = np.minimum(da, dr)
        cls = np.where(walk, 1, np.where(near <= PM5_M, 2, np.where(near <= PM10_M, 3, 4)))
        if dongs[i]["sgg"] in stop_gap:
            cls[:] = 5
        if rr is not None:
            img[rr, cc] = cls
        cov[i] = [b.mean(), (dr <= RAIL_M).mean(), (b | (dr <= RAIL_M)).mean(), w.mean()] + [(cls == k).mean() for k in (1, 2, 3, 4)]
    write_grid(img, W, H)

    # destinations and context
    n_store, store_ok, store_ym = load_stores(tree, dongs)
    ind, ind_lost = load_industrial(dongs)
    lh, lh_n, lh_addr = load_lh(dongs)
    age, age_ym = load_age(dongs)
    ad = load("age_dong.json") if os.path.exists(os.path.join(RAW, "age_dong.json")) else {"ym": None, "dongs": {}}
    dage = [ad["dongs"].get(d["code"]) for d in dongs]  # [total, 20–39, 70+]
    print(f"stores: {int(n_store.sum()):,} in {len(store_ok)} 시군구 ({store_ym or '-'}); 산업단지: {sum(v['n'] for v in ind.values())} in {len(ind)} 시군구, "
          f"not mapped {', '.join(ind_lost) or '-'}; LH: {lh_addr} of {lh_n} 단지 with an address, {len(lh)} 시군구; "
          f"age ({age_ym or '-'}): {len(age)} 시군구, 행정동 {sum(x is not None for x in dage)} ({ad['ym'] or '-'})", flush=True)

    # PM potential: mean percentile rank of PM-reachable share, population density, store density and, once the 행정동
    # age data is there, the share of residents aged 20–39 (PM's main users)
    use_age = sum(x is not None for x in dage) > 0.9 * len(dongs)
    has = [i for i, d in enumerate(dongs) if d["sgg"] not in stop_gap and d["sgg"] in store_ok and pop[i] is not None
           and (not use_age or (dage[i] and dage[i][0]))]
    pm_index = [None] * len(dongs)
    if has:
        def ranks(v):
            o = np.argsort(np.argsort(v))
            return o / max(len(v) - 1, 1)
        idx = np.array(has)
        parts = [ranks(cov[idx, 5] + cov[idx, 6]), ranks(np.array([pop[i] for i in has]) / area[idx]), ranks(n_store[idx] / area[idx])]
        if use_age:
            parts.append(ranks(np.array([dage[i][1] / dage[i][0] for i in has])))
        score = sum(parts) / len(parts)
        for i, v in zip(has, score):
            pm_index[i] = round(float(v) * 100, 1)

    # per 행정동
    n_stop, n_known, n_few, sum_rte = (np.zeros(len(dongs)) for _ in range(4))
    for j in range(len(s_lon)):
        i = s_dong[j]
        n_stop[i] += 1
        if s_rte_ok[j] >= 0:
            n_known[i] += 1
            n_few[i] += s_rte_ok[j] < GOOD_ROUTES
            sum_rte[i] += s_rte_ok[j]
    cols = ["code", "name", "sido", "sidonm", "sgg", "sggnm", "type", "pop", "area_km2", "stops", "stops_known", "stops_few",
            "routes_sum", "bus500", "rail1k", "either", "good500", "route_ok", "osm_fill", "stop_gap",
            "walk", "pm5", "pm10", "far", "stores", "pm_index", "y2039", "o70"]
    rows = []
    for i, d in enumerate(dongs):
        ok, gap = d["sgg"] in route_ok, d["sgg"] in stop_gap
        rows.append([d["code"], d["name"], d["sido"], d["sidonm"], d["sgg"], d["sggnm"], dong_type(d["name"]), pop[i],
                     round(area[i] / 1e6, 3), int(n_stop[i]), int(n_known[i]), int(n_few[i]), int(sum_rte[i]),
                     None if gap else round(cov[i, 0], 4), round(cov[i, 1], 4), None if gap else round(cov[i, 2], 4),
                     round(cov[i, 3], 4) if ok and not gap else None, int(ok), int(d["sgg"] in fill), int(gap)]
                    + ([None] * 4 if gap else [round(cov[i, k], 4) for k in (4, 5, 6, 7)])
                    + [int(n_store[i]) if d["sgg"] in store_ok else None, pm_index[i]]
                    + ([round(dage[i][1] / dage[i][0], 4), round(dage[i][2] / dage[i][0], 4)] if dage[i] and dage[i][0] else [None, None]))
    a = area / 1e6
    u = np.array([dong_type(d["name"]) == "동" for d in dongs])
    print(f"coverage (area-weighted): bus {np.sum(cov[:, 0] * a) / a.sum():.1%}, rail {np.sum(cov[:, 1] * a) / a.sum():.1%}, "
          f"either {np.sum(cov[:, 2] * a) / a.sum():.1%}; 동 only bus {np.sum(cov[u, 0] * a[u]) / a[u].sum():.1%}; "
          f"동 only walk / PM 5 / PM 10 / beyond: " + " / ".join(f"{np.sum(cov[u, k] * a[u]) / a[u].sum():.1%}" for k in (4, 5, 6, 7)), flush=True)

    trips, tmonths, tlost = load_trips(dongs)
    print(f"trips: {len(trips)} 시군구 (months {', '.join(tmonths) or '-'}), "
          f"{sum('transfer' in v for v in trips.values())} with 환승; not mapped: {', '.join(tlost) or '-'}", flush=True)
    sgg_trips = {g: {"day": round(v["modes"]["day"], 1), "modes": {m: round(x, 1) for m, x in v["modes"]["by_mode"].items()},
                     "users": {u: round(x, 1) for u, x in v["modes"]["by_user"].items()},
                     "transfer": round(v["transfer"]["day"], 1) if "transfer" in v else None}
                 for g, v in trips.items() if "modes" in v}
    upis, upis_year = load_upis(dongs)
    nogo = sorted({d["sidonm"] + " " + d["sggnm"] for d in dongs if d["sgg"] not in upis})
    print(f"도시지역 ({upis_year}): {len(upis)} of {len(set(sgg_of))} 시군구; without: {', '.join(nogo) or '-'}", flush=True)
    meta = {"boundary": adm["ver"], "trips_months": tmonths, "upis_year": upis_year, "pop_ym": pop_raw["ym"], "stops_collected": sm["collected"], "route_days": rdays,
            "n_stops": int(len(s_lon)), "n_osm_added": int(add.sum()), "n_stations": len(stations), "stores_ym": store_ym, "age_ym": age_ym, "age_dong_ym": ad["ym"], "pm_index_age": use_age,
            "industrial_date": next(iter(ind.values()))["date"] if ind else None, "lh_table": lh_table(),
            "bus_m": BUS_M, "rail_m": RAIL_M, "grid_m": round(PIX_M * math.cos(math.radians(36))), "good_routes": GOOD_ROUTES,
            "pm_speed": PM_SPEED_KMH, "pm_detour": PM_DETOUR, "pm5_m": PM5_M, "pm10_m": PM10_M,
            "grid_bounds": [[LON0, inv_merc_y(merc_y(LAT1))], [LON0 + np.degrees(W * PIX_M / R_EARTH), inv_merc_y(merc_y(LAT1) - H * PIX_M)]]}
    with open(os.path.join(OUT, "stats.json"), "w", encoding="utf-8") as f:
        json.dump({"meta": meta, "cols": cols, "rows": rows, "sgg_trips": sgg_trips, "sgg_urban": upis, "sgg_industrial": ind, "sgg_lh": lh, "sgg_age": age},
                  f, ensure_ascii=False, separators=(",", ":"))
    feats = []
    for i, g in enumerate(geoms):
        s = shapely.simplify(g, SIMPLIFY_DEG, preserve_topology=True)
        gj = json.loads(shapely.to_geojson(shapely.set_precision(s, 0.00001)))
        feats.append({"type": "Feature", "id": i, "properties": {}, "geometry": gj})
    with open(os.path.join(OUT, "dongs.geojson"), "w", encoding="utf-8") as f:
        json.dump({"type": "FeatureCollection", "features": feats}, f, separators=(",", ":"))
    with open(os.path.join(OUT, "stops.json"), "w", encoding="utf-8") as f:
        json.dump([[round(lo, 5), round(la, 5), int(r), int(sr)] for lo, la, r, sr in zip(s_lon, s_lat, s_rte_ok, s_src)], f, separators=(",", ":"))
    with open(os.path.join(OUT, "stations.json"), "w", encoding="utf-8") as f:
        json.dump(stations, f, ensure_ascii=False, separators=(",", ":"))
    with open(os.path.join(OUT, "download", "dongs.csv"), "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["행정동코드", "행정동", "시도코드", "시도", "시군구코드", "시군구", "구분", "주민등록인구", "면적_km2", "정류장수",
                    "노선수확인정류장", f"노선{GOOD_ROUTES - 1}개이하정류장", "정차노선합계", f"버스{BUS_M}m권역비율",
                    f"철도{RAIL_M}m권역비율", "버스또는철도권역비율", f"노선{GOOD_ROUTES}개이상정류장{BUS_M}m권역비율",
                    "노선수자료있음", "OSM정류장보완", "정류장위치자료부족", "도보권비율", "PM5분권비율", "PM10분권비율",
                    "PM으로도먼곳비율", "상가업소수", "PM잠재지수", "20~39세비중", "70세이상비중"])
        w.writerows(rows)
    for name in ("stats.json", "dongs.geojson", "stops.json", "stations.json", "pmgrid.png"):
        print(f"  {name}: {os.path.getsize(os.path.join(OUT, name)) / 1e6:.1f} MB", flush=True)


if __name__ == "__main__":
    main()
