"""Build site/data from raw/ (see fetch.py for the sources).

1. Bus stops: the 국토교통부 file, plus OpenStreetMap stops in 시군구 the file barely covers (fewer than OSM_FILL of
   the OSM count there); an OSM stop within DEDUP_M of a 국토부 stop is the same stop.
2. Route counts (정차 노선수) are attached to stops by name within the same 시군구 (the API has names and 법정동 codes
   but no coordinates): by 시군구 code, else by 시군구 name (the API keeps pre-2026 codes, so its 시도 are mapped onto
   the current ones, SIDO_GROUP), else (인천's new 구) by a name unique within the 시도. A 시군구 whose stops match less than
   ROUTE_MATCH_MIN gets no route figures. A non-dense 시군구 with fewer than GAP_STOPS_PER_1000 stops per 1,000 people
   lacks stop data in both sources (e.g. 화천, 속초) and gets no bus figures instead of a false gap; so does one with fewer
   than GAP_STOPS_PER_HAB_KM2 stops per ㎢ of 생활권 land (e.g. 평창, 인제, 영광: a few dozen stops for whole 군).
3. Coverage per 행정동 on a Web Mercator pixel grid (~170 m): the share of its area within BUS_M of a bus stop, within
   RAIL_M of a railway station, and within BUS_M of a well-served stop (GOOD_ROUTES or more routes, or routes unknown:
   a stop whose name matched no 정차 노선수 entry gets the benefit of the doubt rather than counting as sparse); and the
   PM classes of GRID_CLASSES (도보권, PM 5분권, PM 10분권, beyond) around PM anchors (stations and well-served stops),
   drawn as pmgrid.png. Distances are straight lines. A PM 5/10분권 cell is 경사로 PM 곤란 when the mean grade to its
   anchor (elevation difference over the riding distance) exceeds GRADE_MAX or its own terrain slope exceeds SLOPE_MAX,
   both on an elevation model cleaned of buildings (see load_terrain).
   Every share is computed twice: over the whole area, and over 생활권 land only, each cell weighted by its share of
   ESA WorldCover classes HABITABLE (built-up, cropland, grassland, bare): forests, water and wetlands are left out.
3b. PM 잠재 지수 per 행정동: geometric mean of the percentile ranks of the PM-reachable share (생활권 land, steep
    cells excluded), population and 상가 density per km² of 생활권 land, and (once the 행정동 age data is there) the share of residents aged 20–39. A 행정동 whose PM-reachable
    share is under PM_INDEX_MIN scores 0: density alone (central Seoul, all within walking distance) is no PM gap.
3c. 산업단지 (한국산업단지공단), LH 임대 세대 and age structure (20–39, 70+) per 시군구.
4. 행정동 type from the name: 동 (urban 행정구역), 읍, 면.
5. Monthly 교통카드 trips per 시군구 (교통수단별 이용량, 환승 이용량), as a daily average of 출발·승차 통행. Under
   TRIPS_MIN trips per resident a day the card data barely covers the 시군구 (e.g. 곡성·음성·청송, a few dozen trips a
   day; all of them lack stop-level route counts too), so it is flagged sparse instead of read as no riders.
5b. 공유 PM 운영 per 시군구 (end of 2024) from scripts/static/pm_ops.csv, read off the 국토교통부 survey map (see
    pm_ops_csv.py).
6. 법정 도시지역 (국토계획법 용도지역) area and population shares per 시군구 from the 도시계획현황 statistics.

Outputs (site/data): dongs.geojson (simplified boundaries), stats.json (one row per 행정동 + metadata), stops.json,
stations.json, pmgrid.png, download/dongs.csv.
"""
import calendar
import collections
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
from scipy import ndimage
from scipy.spatial import cKDTree
from scipy.stats import rankdata

RAW = os.path.join(os.path.dirname(__file__), "..", "raw")
OUT = os.path.join(os.path.dirname(__file__), "..", "site", "data")
BUS_M, RAIL_M = 500, 500  # walking reach of a stop or station: 국토교통부's DRT access test (출발지 500m 이내 정류장, 2025 첨단모빌리티 현황조사)
GOOD_ROUTES = 3  # a stop with fewer routes counts as sparsely served
OSM_FILL, DEDUP_M = 0.5, 50
ROUTE_MATCH_MIN = 0.6
GAP_STOPS_PER_1000, GAP_DENSITY = 2.0, 3000  # a non-dense 시군구 (people per ㎢) with fewer stops per 1,000 people lacks stop data
GAP_STOPS_PER_HAB_KM2 = 1.0  # …as does one with fewer stops per ㎢ of 생활권 land (the median 시군구 has about 10)
SIDO_GROUP = {"29": "12", "46": "12", "42": "51", "45": "52"}  # 광주·전남 → 전남광주통합특별시, old 강원·전북 codes
SIMPLIFY_DEG = 0.0004  # ~40 m
# PM first/last mile (Geurs & van Wee's contour measure): reach within 5 and 10 minutes of riding, as straight lines
PM_SPEED_KMH, PM_DETOUR = 15, 1.3  # assumed average riding speed and road distance / straight distance
PM5_M, PM10_M = (round(PM_SPEED_KMH * 1000 / 60 * m / PM_DETOUR) for m in (5, 10))
PM_INDEX_MIN = 0.10  # PM 10분권 share under which a 행정동's PM 잠재 지수 is 0
TRIPS_MIN = 0.02  # 교통카드 trips per resident a day under which a 시군구's card data counts as sparse
# Web Mercator pixel grid over South Korea (under 4096 px a side, the usual WebGL texture limit); ~170 m at 36°N
LON0, LON1, LAT0, LAT1, PIX_M, R_EARTH = 124.5, 132.0, 33.0, 38.7, 210, 6378137.0
GRID_CLASSES = {1: ("도보권", None), 2: ("PM 5분권", (235, 104, 52, 210)), 3: ("PM 10분권", (246, 179, 143, 190)),
                4: ("PM으로도 먼 곳", (82, 81, 78, 130)), 5: ("정류장 자료 부족", (214, 213, 208, 170)),
                6: ("경사로 PM 곤란", (24, 118, 110, 190)), 7: ("산림·수면 (생활권 밖)", (150, 168, 128, 95))}  # 0: outside Korea
# Slope (assumed thresholds, see about.html for the sensitivity): mean grade from a cell to its PM anchor, and the cell's own
# terrain slope. The elevation model is SRTM-based and includes buildings: an opening over OPEN_PX pixels (≈ 300 m) removes
# narrower bumps (apartment blocks) and a Gaussian of SMOOTH_PX smooths what is left; flat high-rise areas (잠실, 여의도) then
# read 1–1.5% and real hillside neighbourhoods (부산 감천·초량, 해방촌) 14–16%.
GRADE_MAX, SLOPE_MAX = 0.06, 0.10
STEEP_SENS = [(0.04, 0.08), (0.06, 0.10), (0.08, 0.15)]  # (grade, slope) pairs reported for sensitivity
OPEN_PX, SMOOTH_PX, SPIKE_M = 5, 2, 150
HABITABLE = (30, 40, 50, 60)  # ESA WorldCover: grassland, cropland, built-up, bare / sparse vegetation
HAB_MIN_KM2 = 0.05  # floor of the 생활권 area used for densities
COV = ["bus", "rail", "either", "good", "walk", "pm5", "pm10", "steep", "far"]  # coverage shares per 행정동


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


def load_terrain():
    """Cleaned elevation (m) and terrain slope (rise / run) on the mosaic of raw/terrain.npz, and a function giving the
    mosaic (row, col) of lon/lat; None if the file is missing. Spikes (a pixel more than SPIKE_M off its 3×3 median) take
    that median; sea is set to 0 m first so the coast is not dragged down."""
    path = os.path.join(RAW, "terrain.npz")
    if not os.path.exists(path):
        return None
    d = np.load(path)
    dem = d["dem"].astype(np.float32) / 10
    z, x0, y0 = int(d["z"]), int(d["x0"]), int(d["y0"])
    np.maximum(dem, 0, out=dem)
    med = ndimage.median_filter(dem, 3)
    bad = np.abs(dem - med) > SPIKE_M
    dem[bad] = med[bad]
    del med
    dem = ndimage.gaussian_filter(ndimage.grey_opening(dem, size=OPEN_PX), SMOOTH_PX)
    n = 2 ** z * 256
    lat = np.degrees(np.arctan(np.sinh(np.pi * (1 - 2 * (y0 * 256 + np.arange(dem.shape[0]) + 0.5) / n))))
    res = (2 * np.pi * R_EARTH / n * np.cos(np.radians(lat))).astype(np.float32)[:, None]
    gy, gx = np.gradient(dem)
    slope = np.hypot(gx / res, gy / res)
    del gx, gy

    def at(lon, lat):
        lon, lat = np.asarray(lon, float), np.asarray(lat, float)
        c = ((lon + 180) / 360 * n - x0 * 256).astype(int)
        r = ((1 - np.arcsinh(np.tan(np.radians(lat))) / np.pi) / 2 * n - y0 * 256).astype(int)
        return np.clip(r, 0, dem.shape[0] - 1), np.clip(c, 0, dem.shape[1] - 1)
    print(f"terrain: z{z}, {dem.shape[1]} x {dem.shape[0]} px, {int(bad.sum())} spikes fixed, max {dem.max():.0f} m", flush=True)
    return dem, slope, at


def load_habitable(w, h):
    """Share of 생활권 land (WorldCover HABITABLE) in each cell of the W × H build grid, from raw/landcover.npz (all 1 if
    the file is missing). The land cover raster is finer than the grid, so its pixels are summed per cell."""
    path = os.path.join(RAW, "landcover.npz")
    if not os.path.exists(path):
        return None
    d = np.load(path)
    lc, lon0, lat1, k = d["lc"], float(d["lon0"]), float(d["lat1"]), int(d["per_deg"])
    col = np.floor((merc_x(lon0 + (np.arange(lc.shape[1]) + 0.5) / k) - merc_x(LON0)) / PIX_M).astype(int)
    row = np.floor((merc_y(LAT1) - merc_y(lat1 - (np.arange(lc.shape[0]) + 0.5) / k)) / PIX_M).astype(int)
    cs, rs = np.where((col >= 0) & (col < w))[0], np.where((row >= 0) & (row < h))[0]
    hab = np.isin(lc[rs[0]:rs[-1] + 1, cs[0]:cs[-1] + 1], HABITABLE).astype(np.int32)
    col, row = col[cs[0]:cs[-1] + 1], row[rs[0]:rs[-1] + 1]
    c0 = np.r_[0, np.where(np.diff(col))[0] + 1]
    r0 = np.r_[0, np.where(np.diff(row))[0] + 1]
    sums = np.add.reduceat(np.add.reduceat(hab, c0, axis=1), r0, axis=0)
    cnt = np.diff(np.r_[r0, len(row)])[:, None] * np.diff(np.r_[c0, len(col)])[None, :]
    out = np.ones((h, w), np.float32)
    out[row[r0][0]:row[r0][-1] + 1, col[c0][0]:col[c0][-1] + 1] = sums / cnt
    print(f"생활권 land: {np.mean(np.isin(lc, HABITABLE)):.1%} of the land cover raster", flush=True)
    return out


def write_grid(img, w, h):
    """The PM grid as a palette PNG (pmgrid.png); 도보권 and outside are transparent."""
    pal, alpha = [], []
    for k in range(8):
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


def load_ops(dongs, name):
    """운영 (1/0) and 유형 per current 시군구 code from scripts/static/<name> (pm_ops.csv, bike_ops.csv), and its 기준일;
    by code, else by name."""
    path = os.path.join(os.path.dirname(__file__), "static", name)
    if not os.path.exists(path):
        return {}, None
    with open(path, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    by_code = {r["시군구코드"]: r for r in rows}
    by_name = {(r["시도"], r["시군구"]): r for r in rows}
    out = {}
    for d in dongs:
        r = by_code.get(d["sgg"]) or by_name.get((d["sidonm"], d["sggnm"]))
        if r:
            out[d["sgg"]] = [int(r["운영"]), r.get("유형") or ""]
    return out, rows[0]["기준"] if rows else None


def fee_won(text):
    """'30,000원', '15000원', 40000, '30,000원 (예정)' → (30000, planned)."""
    m = re.search(r"\d[\d,]*", str(text or ""))
    return (int(m.group().replace(",", "")) if m else None), "예정" in str(text or "")


def load_ordinance(dongs):
    """PM 조례·견인 per current 시군구 from scripts/static/ordinance.csv (지자체 PM·견인 조례 분석, see ordinance_csv.py).
    The 광역 level comes first: what the 광역지자체 has (PM 조례, 이동조치 규정, PM 견인, 자전거 견인) holds for every
    기초 in it, whatever the 기초 row says. The 견인료 is the 기초's own when it set one, else the 광역's.
    The 2026 전남광주통합특별시 has three 광역 rows: (구)광주광역시 for the former 광주 구, (구)전라남도 for the former 전남
    시군, and 전남광주통합특별시 for all of them. 세종 and 제주's 행정시 have only the 광역 row.
    Returns {sgg: {o, m, t, b: 0/1, fee, planned, src, own: [조례명…], wide: [(광역, 조례명…)]}}."""
    path = os.path.join(os.path.dirname(__file__), "static", "ordinance.csv")
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    yes = lambda v: (v or "").strip().upper() == "Y"
    wide, local = {}, {}
    for r in rows:
        (wide if r["구분"] == "광역" else local)[r["지자체명"].strip()] = r

    def wides(d):
        if d["sido"] == "12":
            old = "(구)광주광역시" if d["sggnm"].endswith("구") else "(구)전라남도"
            return [wide[k] for k in (old, d["sidonm"]) if k in wide]
        return [wide[d["sidonm"]]] if d["sidonm"] in wide else []

    def own(d):
        r = local.get(f"{d['sidonm']} {d['sggnm']}")
        if r is None and "시" in d["sggnm"][:-1] and d["sggnm"].endswith("구"):  # 시 with 구: the 시 row
            r = local.get(f"{d['sidonm']} {d['sggnm'][:d['sggnm'].index('시') + 1]}")
        return r

    out = {}
    for d in dongs:
        if d["sgg"] in out:
            continue
        r, ws = own(d), wides(d)
        both = ([r] if r else []) + ws
        flag = lambda k: int(any(yes(x[k]) for x in both))
        fee, planned, src = None, False, None
        for x in ([r] if r else []) + ws:  # the 기초's own fee first
            if yes(x["견인조례_PM항목"]):
                f_, p_ = fee_won(x["PM_견인료"])
                if f_:
                    fee, planned, src = f_, p_, x["지자체명"]
                    break
        out[d["sgg"]] = {"o": flag("PM조례_유무"), "m": flag("이동조치규정_유무"), "t": flag("견인조례_PM항목"),
                         "b": flag("자전거 견인 여부"), "fee": fee, "planned": planned, "src": src,
                         "own": [n for n in ((r or {}).get("PM조례명"), (r or {}).get("견인조례명")) if n],
                         "wide": [[x["지자체명"], *[n for n in (x.get("PM조례명"), x.get("견인조례명")) if n]] for x in ws]}
    return out


def region_resolver(dongs):
    """A function '강원 춘천시' / '충남 천안' / '경기 수원시' / '서울특별시' / '광주-남구' → the current 시군구 codes it covers:
    the 시군구 itself, every 구 of a 시 with 구, a whole 시도 named alone, 인천's former 중구·서구 their successors."""
    sggs, sido_all = {}, defaultdict(set)
    for x in dongs:
        sggs.setdefault((x["sido"], x["sggnm"]), x["sgg"])
        sido_all[x["sidonm"]].add(x["sgg"])

    def codes(region):
        region = re.sub(r"\(.*?\)", "", str(region or "")).strip()
        if region in sido_all:
            return sorted(sido_all[region])
        if region == "광주광역시":  # merged into 전남광주통합특별시 in 2026: its former 구
            return sorted(g for (s_, n), g in sggs.items() if s_ == "12" and n.endswith("구"))
        parts = re.split(r"[-\s]", region, maxsplit=1)
        sido, name = IND_SIDO.get(parts[0]), parts[-1].strip()
        if (sido, name) in sggs:
            return [sggs[(sido, name)]]
        if ACC_OLD.get((sido, name)):
            return [sggs[(sido, n)] for n in ACC_OLD[(sido, name)] if (sido, n) in sggs]
        city = [g for (s_, n), g in sggs.items() if s_ == sido and name.endswith("시") and n.startswith(name) and n != name]
        if city:
            return sorted(city)
        bare = [g for (s_, n), g in sggs.items() if s_ == sido and n[:-1] == name and n[-1] in "시군구"]  # '천안' → 천안시
        if len(bare) == 1:
            return bare
        bare = [g for (s_, n), g in sggs.items() if s_ == sido and n.startswith(name + "시") and n != name + "시"]  # '천안' → its 구
        return sorted(bare)
    return codes


SURVEY_DATE = "2024-12-31"
SURVEY_SRC = "국토교통부 2025년 첨단모빌리티 현황조사 (2024년 말)"


def load_survey():
    """scripts/static/kotsa_2025.csv: the survey's tables per 지역 (2024년 말): 공유 PM 운영 대수 [표 2-16] and 이용 횟수
    [표 2-17, 모바일 앱 사용량 기반], 공유자전거 공영·민영 운영 대수 and 민영 이용 횟수 [표 2-15]."""
    path = os.path.join(os.path.dirname(__file__), "static", "kotsa_2025.csv")
    if not os.path.exists(path):
        return []
    out = []
    with open(path, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            num = lambda k: float(r[k]) if r[k] != "" else None
            out.append({"region": f"{r['시도']} {r['시군구']}".strip(), "pm": int(num("공유PM운영대수")) if r["공유PM운영대수"] else None, "pm_use": num("공유PM이용횟수"),
                        "bike_pub": num("공유자전거공영대수"), "bike_pub_name": r["공영서비스명"], "bike_pri": num("공유자전거민영대수"),
                        "bike_use": num("공유자전거민영이용횟수")})
    return out


def survey_units(survey, codes, unit_name, gpop):
    """The survey's other figures per 지역 unit: [{name, sgg, pop, pm_use, bike_pub, bike_pub_name, bike_pri, bike_use}]."""
    out = []
    for r in survey:
        cs = codes(r["region"])
        if cs and any(r[k] is not None for k in ("pm_use", "bike_pub", "bike_pri", "bike_use")):
            out.append({"name": unit_name(cs), "sgg": cs, "pop": sum(gpop[g] for g in cs),
                        **{k: r[k] for k in ("pm_use", "bike_pub", "bike_pub_name", "bike_pri", "bike_use")}})
    return out


def write_pm_supply(dongs, pop, tree):
    """PM 기기 수 and 주차구역 (site/data/pm.json): units (one per 지역 of the sources, as current 시군구 codes) with their
    devices (전동킥보드, 전기자전거, or not told apart), 운영사 (named, else a count), 기준일 and source; the 서울 companies per 구;
    and the parking points with the 시군구 they fall in. Each source keeps its own 기준일."""
    codes = region_resolver(dongs)
    info = {x["sgg"]: (x["sidonm"], x["sggnm"]) for x in dongs}
    sido_n = collections.Counter(v[0] for v in info.values())

    gwangju = sorted(codes("광주광역시"))

    def unit_name(cs):  # 시도 alone, a 시 with 구 by the 시, else the 시군구
        if len(cs) > 1 and sorted(cs) == gwangju:
            return "광주광역시 (2026년 통합 전)"
        sd = {info[g][0] for g in cs}
        if len(sd) == 1 and len(cs) == sido_n[next(iter(sd))] and len(cs) > 1:
            return next(iter(sd))
        names = [info[g][1] for g in cs]
        if len(names) > 1 and all("시" in n[:-1] for n in names) and len({n[:n.index("시") + 1] for n in names}) == 1:
            return f"{info[cs[0]][0]} {names[0][:names[0].index('시') + 1]}"
        return f"{info[cs[0]][0]} " + "·".join(names)
    gpop = defaultdict(int)
    for x, p in zip(dongs, pop):
        gpop[x["sgg"]] += p or 0
    recs = load("pm_fleet.json")["records"] if os.path.exists(os.path.join(RAW, "pm_fleet.json")) else []
    path = os.path.join(os.path.dirname(__file__), "static", "pm_fleet_static.csv")
    seoul_gu = defaultdict(set)
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            for r in csv.DictReader(f):
                num = lambda k: int(r[k]) if r[k] else None
                recs.append({"region": r["지역"], "operator": None, "ops_n": num("업체수"), "kick": num("전동킥보드"), "bike": num("전기자전거"),
                             "total": num("합계(구분없음)"), "date": r["기준일"], "source": r["출처"], "company": r["운영사"] or None})
                if r["지역"] == "서울특별시":
                    for gu in r["비고(운영구·종류)"].split(","):
                        seoul_gu[gu.strip()].add(r["운영사"])
    survey = load_survey()
    for r in survey:
        if r["pm"] is not None:
            recs.append({"region": r["region"], "operator": None, "ops_n": None, "kick": None, "bike": None, "total": r["pm"],
                         "date": SURVEY_DATE, "source": SURVEY_SRC + " [표 2-16]"})
    # one unit per 지역 and source; each 시군구 then takes the newest unit covering it (the more specific on a tie)
    units, lost = {}, collections.Counter()
    for r in recs:
        cs = codes(r["region"])
        if not cs:
            lost[r["region"]] += 1
            continue
        u = units.setdefault((tuple(cs), r["source"]), {"name": unit_name(cs), "sgg": cs, "pop": sum(gpop[g] for g in cs),
                                          "kick": 0, "bike": 0, "mixed": 0, "ops": collections.Counter(), "ops_n": 0, "companies": set(),
                                          "dates": set(), "sources": set()})
        for k in ("kick", "bike"):
            u[k] += r[k] or 0
        u["mixed"] += r["total"] or 0
        if r["operator"]:
            u["ops"][r["operator"]] += (r["kick"] or 0) + (r["bike"] or 0) + (r["total"] or 0)
        if r.get("company"):
            u["companies"].add(r["company"])
        u["ops_n"] = max(u["ops_n"], r["ops_n"] or 0)
        u["dates"].add(r["date"] or "")
        u["sources"].add(r["source"])
    ulist = list(units.values())
    for u in ulist:
        u["date"] = max((d for d in u["dates"] if d), default="")
    pick = {}
    for i, u in enumerate(ulist):
        for g in u["sgg"]:
            j = pick.get(g)
            if j is None or (u["date"], -len(u["sgg"])) > (ulist[j]["date"], -len(ulist[j]["sgg"])):
                pick[g] = i
    used = sorted(set(pick.values()))
    fleet, by_sgg = [], {}
    for i in used:
        u = ulist[i]
        n_ops = len(u["ops"]) or len(u["companies"]) or u["ops_n"] or None
        mine = [g for g in u["sgg"] if pick[g] == i]
        fleet.append({"name": u["name"], "sgg": u["sgg"], "pop": u["pop"], "kick": u["kick"] or None, "bike": u["bike"] or None,
                      "mixed": u["mixed"] or None, "total": u["kick"] + u["bike"] + u["mixed"],
                      "ops": [[o, n] for o, n in u["ops"].most_common()], "n_ops": n_ops,
                      "date": " · ".join(sorted(d for d in u["dates"] if d)), "source": " · ".join(sorted(u["sources"])),
                      "partial": len(mine) < len(u["sgg"])})  # some of its 시군구 have newer or finer figures: left out of totals
        for g in mine:
            by_sgg[g] = len(fleet) - 1
    dropped = [f"{u['name']} {u['date']}" for i, u in enumerate(ulist) if i not in set(used)]
    # 서울: devices only for the whole city; companies per 구
    sgg_by_name = {(x["sidonm"], x["sggnm"]): x["sgg"] for x in dongs}
    seoul = {sgg_by_name[("서울특별시", gu)]: len(cs) for gu, cs in seoul_gu.items() if ("서울특별시", gu) in sgg_by_name}

    pts = load("pm_parking.json")["points"] if os.path.exists(os.path.join(RAW, "pm_parking.json")) else []
    path = os.path.join(os.path.dirname(__file__), "static", "pm_parking_static.csv")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            pts += [{"region": r["지역"], "name": r["명칭"], "kind": r["형태"], "cap": r["주차대수"] or None, "lon": float(r["경도"]),
                     "lat": float(r["위도"]), "date": r["기준일"], "source": r["출처"]} for r in csv.DictReader(f)]
    sources = sorted({(p["source"], p["date"] or "") for p in pts})
    si = {s_: i for i, s_ in enumerate(sources)}
    # counts per 지역 unit (a 시 with 구 as one, since a source names only the 시 and some points lack coordinates)
    punits, plost = {}, collections.Counter()
    for g in (g for region in PARKING_WHOLE for g in codes(region)):
        punits[(g,)] = {"name": unit_name([g]), "sgg": [g], "n": 0, "dates": set(), "sources": set()}
    for p in pts:
        cs = codes(p["region"])
        if not cs:
            plost[p["region"]] += 1
            continue
        u = punits.setdefault(tuple(cs), {"name": unit_name(cs), "sgg": cs, "n": 0, "dates": set(), "sources": set()})
        u["n"] += 1
        u["dates"].add(p["date"] or "")
        u["sources"].add(p["source"])
    parking_units = [{"name": u["name"], "sgg": u["sgg"], "n": u["n"], "date": " · ".join(sorted(d for d in u["dates"] if d)),
                      "source": " · ".join(sorted(u["sources"]))} for u in punits.values()]
    xy = [p for p in pts if p["lon"] and p["lat"]]
    park = [[round(p["lon"], 6), round(p["lat"], 6), p["name"] or "", p["kind"] or "", str(p["cap"] or ""), si[(p["source"], p["date"] or "")]]
            for p in xy]
    with open(os.path.join(OUT, "pm.json"), "w", encoding="utf-8") as f:
        json.dump({"fleet": fleet, "fleet_by_sgg": by_sgg, "survey": survey_units(survey, codes, unit_name, gpop), "survey_date": SURVEY_DATE,
                   "seoul_companies": seoul, "parking": park, "parking_sources": sources, "parking_units": parking_units},
                  f, ensure_ascii=False, separators=(",", ":"))
    print(f"PM fleet: {len(fleet)} units ({sum(u['partial'] for u in fleet)} partly superseded), "
          f"{sum(u['total'] for u in fleet if not u['partial']):,} devices; superseded by newer figures: {', '.join(dropped) or '-'}; not mapped: "
          + (", ".join(f"{k} {v}" for k, v in lost.items()) or "-")
          + f"; parking: {len(pts)} zones in {len(parking_units)} units ({len(park)} with coordinates), not mapped: "
          + (", ".join(f"{k} {v}" for k, v in plost.items()) or "-"), flush=True)


# parking zones are counted per 지역 named by their source (경기도 lists only the 시군 that reported); 서울's file covers the
# whole city, so a 구 it does not name has none
PARKING_WHOLE = ["서울특별시"]
ACC_OLD = {("28", "중구"): ("제물포구", "영종구"), ("28", "서구"): ("서해구", "검단구")}  # 인천 구 before the 2026 reorganization


def write_accidents(dongs, pop):
    """site/data/accidents.json from raw/pm_accidents.json (도로교통공단 PM 교통사고 합성데이터): the regions as units of
    current 시군구 ('경기-수원시' covers every 구 of 수원시; 인천's former 중구·서구 their successor 구; 광주 the 구 of
    전남광주통합특별시) with their population, and one compact row per record."""
    if not os.path.exists(os.path.join(RAW, "pm_accidents.json")):
        return
    d = load("pm_accidents.json")
    resolve = region_resolver(dongs)
    gpop = defaultdict(int)
    for x, p in zip(dongs, pop):
        gpop[x["sgg"]] += p or 0
    units, index, lost = [], {}, collections.Counter()
    rows = []
    for r in d["rows"]:
        region = str(r.get("발생지역") or "")
        if region not in index:
            codes = resolve(region)
            index[region] = len(units) if codes else None
            if codes:
                units.append({"name": region.replace("-", " "), "sgg": sorted(codes), "pop": sum(gpop[g] for g in codes)})
        if index[region] is None:
            lost[region] += 1
            continue
        rows.append([index[region], r.get("사고유형"), r.get("시간대"), r.get("가해자연령대"), r.get("가해자성별"),
                     int(r.get("사망자수") or 0), int(r.get("중상자수") or 0), int(r.get("경상자수") or 0), int(r.get("부상신고자수") or 0)])
    with open(os.path.join(OUT, "accidents.json"), "w", encoding="utf-8") as f:
        json.dump({"meta": {"title": d.get("title"), "date": d.get("date"), "n": len(rows)}, "units": units,
                   "cols": ["unit", "type", "time", "age", "sex", "dead", "serious", "minor", "report"], "rows": rows},
                  f, ensure_ascii=False, separators=(",", ":"))
    print(f"PM accidents ({d.get('title')}): {len(rows)} records in {len(units)} units; not mapped: "
          + (", ".join(f"{k} {v}" for k, v in lost.items()) or "-"), flush=True)


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
    # well-served stops, also the PM anchors (with stations): GOOD_ROUTES+ routes, or route count unknown (a 시군구 without
    # route figures, or a stop whose name matched none: counting those as sparse would rank low-match 시군구 as gaps)
    good = (s_rte_ok >= GOOD_ROUTES) | (s_rte_ok < 0)
    good_t = cKDTree(proj(s_lon[good], s_lat[good]))
    print(f"well-served stops: {good.sum()} ({np.sum(s_rte_ok >= GOOD_ROUTES)} with {GOOD_ROUTES}+ routes, {np.sum(s_rte_ok < 0)} unknown)", flush=True)
    W, H = math.ceil((merc_x(LON1) - merc_x(LON0)) / PIX_M), math.ceil((merc_y(LAT1) - merc_y(LAT0)) / PIX_M)
    img = np.zeros((H, W), np.uint8)  # GRID_CLASSES
    hab_grid = load_habitable(W, H)
    terrain = load_terrain()
    if terrain:
        dem, slope, dem_at = terrain
        h_good = dem[dem_at(s_lon[good], s_lat[good])]
        h_rail = dem[dem_at([s[0] for s in stations], [s[1] for s in stations])]
    cov = np.zeros((len(dongs), len(COV)))  # over the whole area
    cov_h = np.full((len(dongs), len(COV)), np.nan)  # over 생활권 land
    hab = np.ones(len(dongs))  # 생활권 share of the 행정동
    sens = np.zeros((len(dongs), len(STEEP_SENS) + 1))  # 생활권 PM 5/10분권 area that would be steep, per (grade, slope) pair; last: all
    cells = [None] * len(dongs)  # (rows, cols, 생활권 weights) of the cells drawn for each 행정동
    for i, g in enumerate(geoms):
        lo0, la0, lo1, la1 = g.bounds
        c = np.arange(max(0, int((merc_x(lo0) - merc_x(LON0)) / PIX_M)), min(W, int((merc_x(lo1) - merc_x(LON0)) / PIX_M) + 1))
        r = np.arange(max(0, int((merc_y(LAT1) - merc_y(la1)) / PIX_M)), min(H, int((merc_y(LAT1) - merc_y(la0)) / PIX_M) + 1))
        C_, R_ = np.meshgrid(c, r)
        lon = LON0 + np.degrees((C_.ravel() + 0.5) * PIX_M / R_EARTH)
        lat = inv_merc_y(merc_y(LAT1) - (R_.ravel() + 0.5) * PIX_M)
        inside = shapely.contains_xy(g, lon, lat)
        if inside.any():
            lon, lat, rr, cc = lon[inside], lat[inside], R_.ravel()[inside], C_.ravel()[inside]
            draw = True
        else:  # smaller than a pixel
            p = g.representative_point()
            lon, lat = np.array([p.x]), np.array([p.y])
            rr = np.clip([int((merc_y(LAT1) - merc_y(p.y)) / PIX_M)], 0, H - 1)
            cc = np.clip([int((merc_x(p.x) - merc_x(LON0)) / PIX_M)], 0, W - 1)
            draw = False
        pts = proj(lon, lat)
        b = bus_t.query(pts, distance_upper_bound=BUS_M)[0] <= BUS_M
        dr, ir = rail_t.query(pts, distance_upper_bound=PM10_M)
        da, ia = good_t.query(pts, distance_upper_bound=PM10_M)
        w = da <= BUS_M
        walk = (da <= BUS_M) | (dr <= RAIL_M)
        near = np.minimum(da, dr)
        cls = np.where(walk, 1, np.where(near <= PM5_M, 2, np.where(near <= PM10_M, 3, 4)))
        hw = hab_grid[rr, cc] if hab_grid is not None else np.ones(len(cls))
        pm = (cls == 2) | (cls == 3)
        if terrain and pm.any():
            hc = dem[dem_at(lon, lat)]
            ha = np.where(da <= dr, h_good[np.minimum(ia, len(h_good) - 1)], h_rail[np.minimum(ir, len(h_rail) - 1)])
            grade = np.abs(hc - ha) / np.maximum(near * PM_DETOUR, 1)
            sl = slope[dem_at(lon, lat)]
            for k, (gmax, smax) in enumerate(STEEP_SENS):
                sens[i, k] = np.sum(hw * (pm & ((grade > gmax) | (sl > smax))))
            cls[pm & ((grade > GRADE_MAX) | (sl > SLOPE_MAX))] = 6
        sens[i, -1] = np.sum(hw * pm)
        if draw:
            img[rr, cc] = np.where(hw < 0.5, 7, cls)
            cells[i] = (rr, cc, hw)
        parts = [b, dr <= RAIL_M, b | (dr <= RAIL_M), w] + [cls == k for k in (1, 2, 3, 6, 4)]
        cov[i] = [x.mean() for x in parts]
        hab[i] = hw.mean()
        if hw.sum() > 0:
            cov_h[i] = [np.sum(hw * x) / hw.sum() for x in parts]
    # stop data gaps by 생활권 area (needs the land cover per 행정동, so only now): no bus figures, grey on the PM grid
    if hab_grid is not None:
        g_hab, g_lack = defaultdict(float), set()
        for i, d in enumerate(dongs):
            g_hab[d["sgg"]] += area[i] / 1e6 * hab[i]
        g_lack = {g for g in g_hab if g_hab[g] and g_stop[g] / g_hab[g] < GAP_STOPS_PER_HAB_KM2} - stop_gap
        print("stop data gaps by 생활권 area: " + (", ".join(sorted(f"{dongs[np.where(sgg_of == g)[0][0]]['sggnm']}({g_stop[g]} stops, "
              f"{g_hab[g]:.0f}㎢)" for g in g_lack)) or "-"), flush=True)
        stop_gap |= g_lack
    for i, d in enumerate(dongs):
        if d["sgg"] in stop_gap and cells[i]:
            rr, cc, hw = cells[i]
            img[rr, cc] = np.where(hw < 0.5, 7, 5)
    write_grid(img, W, H)
    u = np.array([dong_type(d["name"]) == "동" and d["sgg"] not in stop_gap for d in dongs])
    s_all, s_u = sens[[d["sgg"] not in stop_gap for d in dongs]].sum(0), sens[u].sum(0)
    steep_sens = [[gmax, smax, round(float(s_all[k] / s_all[-1]), 4), round(float(s_u[k] / s_u[-1]), 4)]
                  for k, (gmax, smax) in enumerate(STEEP_SENS)] if terrain and s_all[-1] and s_u[-1] else None
    if steep_sens:
        print("steep share of 생활권 PM 5/10분권 by (grade, slope): " + ", ".join(f"({a:.0%}, {b:.0%}) {c:.1%} / 동 {e:.1%}" for a, b, c, e in steep_sens), flush=True)
    if terrain:
        del dem, slope, terrain

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

    # PM potential: geometric mean of the percentile ranks of PM-reachable share, population density, store density and,
    # once the 행정동 age data is there, the share of residents aged 20–39 (PM's main users). An arithmetic mean let density
    # carry 행정동 with no PM gap at all to the top (central Seoul); the geometric mean needs every part, and a PM share
    # under PM_INDEX_MIN scores 0.
    use_age = sum(x is not None for x in dage) > 0.9 * len(dongs)
    has = [i for i, d in enumerate(dongs) if d["sgg"] not in stop_gap and d["sgg"] in store_ok and pop[i] is not None
           and (not use_age or (dage[i] and dage[i][0]))]
    pm_index = [None] * len(dongs)
    if has:
        def ranks(v):  # percentile rank in (0, 1), ties share their mean rank
            return (rankdata(v) - 0.5) / len(v)
        idx = np.array(has)
        ch = np.where(np.isnan(cov_h[idx]), cov[idx], cov_h[idx])
        pmv = ch[:, COV.index("pm5")] + ch[:, COV.index("pm10")]
        ok = pmv >= PM_INDEX_MIN
        hab_km2 = np.maximum(area[idx] / 1e6 * hab[idx], HAB_MIN_KM2)
        parts = [np.zeros(len(idx)), ranks(np.array([pop[i] for i in has]) / hab_km2), ranks(n_store[idx] / hab_km2)]
        parts[0][ok] = ranks(pmv[ok])  # among the 행정동 with a PM gap
        if use_age:
            parts.append(ranks(np.array([dage[i][1] / dage[i][0] for i in has])))
        score = np.prod(parts, axis=0) ** (1 / len(parts))
        for i, v in zip(has, score):
            pm_index[i] = round(float(v) * 100, 1)
        print(f"PM index: {len(has)} 행정동, {int(ok.sum())} with PM 10분권 ≥ {PM_INDEX_MIN:.0%}, the rest 0", flush=True)

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
            "routes_sum", "route_ok", "osm_fill", "stop_gap", "stores", "pm_index", "y2039", "o70", "hab",
            "bus500", "rail500", "either", "good500", "walk", "pm5", "pm10", "steep", "far"]
    cols += ["h_" + c for c in cols[-9:]]  # the same shares over 생활권 land

    def shares(v, ok, gap):
        r = lambda x: None if x is None or np.isnan(x) else round(float(x), 4)
        return [None if gap else r(v[0]), r(v[1]), None if gap else r(v[2]), r(v[3]) if ok and not gap else None] \
            + ([None] * 5 if gap else [r(x) for x in v[4:]])
    rows = []
    for i, d in enumerate(dongs):
        ok, gap = d["sgg"] in route_ok, d["sgg"] in stop_gap
        rows.append([d["code"], d["name"], d["sido"], d["sidonm"], d["sgg"], d["sggnm"], dong_type(d["name"]), pop[i],
                     round(area[i] / 1e6, 3), int(n_stop[i]), int(n_known[i]), int(n_few[i]), int(sum_rte[i]),
                     int(ok), int(d["sgg"] in fill), int(gap), int(n_store[i]) if d["sgg"] in store_ok else None, pm_index[i]]
                    + ([round(dage[i][1] / dage[i][0], 4), round(dage[i][2] / dage[i][0], 4)] if dage[i] and dage[i][0] else [None, None])
                    + [round(float(hab[i]), 4)] + shares(cov[i], ok, gap) + shares(cov_h[i], ok, gap))
    a = area / 1e6
    u = np.array([dong_type(d["name"]) == "동" for d in dongs])
    for name, cv, wt in (("whole area", cov, a), ("생활권 land", np.nan_to_num(cov_h), a * hab)):
        print(f"coverage ({name}, area-weighted): either {np.sum(cv[:, 2] * wt) / wt.sum():.1%} outside walking distance "
              f"{1 - np.sum(cv[:, 2] * wt) / wt.sum():.1%}; 동 only walk / PM 5 / PM 10 / steep / beyond: "
              + " / ".join(f"{np.sum(cv[u, COV.index(k)] * wt[u]) / wt[u].sum():.1%}" for k in ("walk", "pm5", "pm10", "steep", "far")), flush=True)
    print(f"생활권 share of the land: {np.sum(a * hab) / a.sum():.1%} (동 {np.sum(a[u] * hab[u]) / a[u].sum():.1%})", flush=True)

    trips, tmonths, tlost = load_trips(dongs)
    print(f"trips: {len(trips)} 시군구 (months {', '.join(tmonths) or '-'}), "
          f"{sum('transfer' in v for v in trips.values())} with 환승; not mapped: {', '.join(tlost) or '-'}", flush=True)
    sgg_trips = {g: {"day": round(v["modes"]["day"], 1), "modes": {m: round(x, 1) for m, x in v["modes"]["by_mode"].items()},
                     "users": {u: round(x, 1) for u, x in v["modes"]["by_user"].items()},
                     "transfer": round(v["transfer"]["day"], 1) if "transfer" in v else None,
                     "sparse": not g_pop[g] or v["modes"]["day"] / g_pop[g] < TRIPS_MIN}
                 for g, v in trips.items() if "modes" in v}
    name_of = lambda g: dongs[np.where(sgg_of == g)[0][0]]["sggnm"]
    print(f"trips sparse (< {TRIPS_MIN} a resident a day): " + ", ".join(sorted(name_of(g) for g, v in sgg_trips.items() if v["sparse"]))
          + "; none: " + (", ".join(sorted(name_of(g) for g in set(sgg_of) if g not in sgg_trips)) or "-"), flush=True)
    upis, upis_year = load_upis(dongs)
    pm_ops, pm_ops_date = load_ops(dongs, "pm_ops.csv")
    bike_ops, _ = load_ops(dongs, "bike_ops.csv")
    for what, ops in (("공유 PM", pm_ops), ("공유자전거", bike_ops)):
        print(f"{what} 운영 ({pm_ops_date or '-'}): {sum(v[0] for v in ops.values())} of {len(ops)} 시군구 operate; "
              f"no figure: {', '.join(sorted({d['sggnm'] for d in dongs if d['sgg'] not in ops})) or '-'}", flush=True)
    ordin = load_ordinance(dongs)
    print(f"조례 ({len(ordin)} 시군구): " + ", ".join(f"{k} {sum(v[k] for v in ordin.values())}" for k in "omtb")
          + f"; 견인료 {sum(v['fee'] is not None for v in ordin.values())} (" + ", ".join(
              f"{fee:,}원 {n}" for fee, n in sorted(collections.Counter(v['fee'] for v in ordin.values() if v['t'] and v['fee']).items())) + ")", flush=True)
    nogo = sorted({d["sidonm"] + " " + d["sggnm"] for d in dongs if d["sgg"] not in upis})
    print(f"도시지역 ({upis_year}): {len(upis)} of {len(set(sgg_of))} 시군구; without: {', '.join(nogo) or '-'}", flush=True)
    meta = {"boundary": adm["ver"], "trips_months": tmonths, "upis_year": upis_year, "pop_ym": pop_raw["ym"], "stops_collected": sm["collected"], "route_days": rdays,
            "n_stops": int(len(s_lon)), "n_osm_added": int(add.sum()), "n_stations": len(stations), "stores_ym": store_ym, "pm_ops_date": pm_ops_date, "age_ym": age_ym, "age_dong_ym": ad["ym"], "pm_index_age": use_age,
            "industrial_date": next(iter(ind.values()))["date"] if ind else None, "lh_table": lh_table(),
            "bus_m": BUS_M, "rail_m": RAIL_M, "grid_m": round(PIX_M * math.cos(math.radians(36))), "good_routes": GOOD_ROUTES,
            "pm_speed": PM_SPEED_KMH, "pm_detour": PM_DETOUR, "pm5_m": PM5_M, "pm10_m": PM10_M, "pm_index_min": PM_INDEX_MIN, "trips_min": TRIPS_MIN,
            "grade_max": GRADE_MAX, "slope_max": SLOPE_MAX,
"steep_sens": steep_sens, "landcover": hab_grid is not None,
            "grid_bounds": [[LON0, inv_merc_y(merc_y(LAT1))], [LON0 + np.degrees(W * PIX_M / R_EARTH), inv_merc_y(merc_y(LAT1) - H * PIX_M)]]}
    with open(os.path.join(OUT, "stats.json"), "w", encoding="utf-8") as f:
        json.dump({"meta": meta, "cols": cols, "rows": rows, "sgg_trips": sgg_trips, "sgg_urban": upis, "sgg_industrial": ind, "sgg_lh": lh, "sgg_age": age, "sgg_pm_ops": {g: v[0] for g, v in pm_ops.items()},
                   "sgg_bike_ops": bike_ops, "sgg_ordinance": ordin},
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
        share = [f"버스{BUS_M}m권역비율", f"철도{RAIL_M}m권역비율", "버스또는철도권역비율", f"노선{GOOD_ROUTES}개이상정류장{BUS_M}m권역비율",
                 "도보권비율", "PM5분권비율", "PM10분권비율", "경사로PM곤란비율", "PM으로도먼곳비율"]
        w.writerow(["행정동코드", "행정동", "시도코드", "시도", "시군구코드", "시군구", "구분", "주민등록인구", "면적_km2", "정류장수",
                    "노선수확인정류장", f"노선{GOOD_ROUTES - 1}개이하정류장", "정차노선합계", "노선수자료있음", "OSM정류장보완",
                    "정류장위치자료부족", "상가업소수", "PM잠재지수", "20~39세비중", "70세이상비중", "생활권면적비중"]
                   + ["전체면적_" + x for x in share] + ["생활권면적_" + x for x in share])
        w.writerows(rows)
    write_accidents(dongs, pop)
    write_pm_supply(dongs, pop, tree)
    for name in ("stats.json", "dongs.geojson", "stops.json", "stations.json", "pmgrid.png"):
        print(f"  {name}: {os.path.getsize(os.path.join(OUT, name)) / 1e6:.1f} MB", flush=True)


if __name__ == "__main__":
    main()
