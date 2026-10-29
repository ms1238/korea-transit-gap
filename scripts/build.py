"""Build site/data from raw/ (see fetch.py for the sources).

1. Bus stops: the 국토교통부 file, plus OpenStreetMap stops in 시군구 the file barely covers (fewer than OSM_FILL of
   the OSM count there); an OSM stop within DEDUP_M of a 국토부 stop is the same stop.
2. Route counts (정차 노선수) are attached to stops by name within the same 시군구 (the API has names and 법정동 codes
   but no coordinates): by 시군구 code, else by 시군구 name (the API keeps pre-2026 codes, so its 시도 are mapped onto
   the current ones, SIDO_GROUP), else (인천's new 구) by a name unique within the 시도. A 시군구 whose stops match less than
   ROUTE_MATCH_MIN gets no route figures.
3. Coverage per 행정동: the share of its area (cells of a GRID_M grid) within BUS_M of a bus stop, within RAIL_M of a
   railway station, and within BUS_M of a stop served by GOOD_ROUTES or more routes. Distances are straight lines.
4. 행정동 type from the name: 동 (urban 행정구역), 읍, 면.
5. Monthly 교통카드 trips per 시군구 (교통수단별 이용량, 환승 이용량), as a daily average of 출발·승차 통행.

Outputs (site/data): dongs.geojson (simplified boundaries), stats.json (one row per 행정동 + metadata), stops.json,
stations.json, download/dongs.csv.
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
from scipy.spatial import cKDTree

RAW = os.path.join(os.path.dirname(__file__), "..", "raw")
OUT = os.path.join(os.path.dirname(__file__), "..", "site", "data")
BUS_M, RAIL_M, GRID_M = 500, 1000, 100
GOOD_ROUTES = 3  # a stop with fewer routes counts as sparsely served
OSM_FILL, DEDUP_M = 0.5, 50
ROUTE_MATCH_MIN = 0.6
SIDO_GROUP = {"29": "12", "46": "12", "42": "51", "45": "52"}  # 광주·전남 → 전남광주통합특별시, old 강원·전북 codes
SIMPLIFY_DEG = 0.0004  # ~40 m


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

    # 3. coverage on a grid
    bus_t = cKDTree(proj(s_lon, s_lat))
    good = s_rte_ok >= GOOD_ROUTES
    good_t = cKDTree(proj(s_lon[good], s_lat[good])) if good.any() else None
    rail_t = cKDTree(proj([s[0] for s in stations], [s[1] for s in stations]))
    cov = np.zeros((len(dongs), 4))  # bus, rail, either, well-served bus
    for i, g in enumerate(pgeoms):
        x0, y0, x1, y1 = g.bounds
        xs = np.arange(math.floor(x0 / GRID_M) * GRID_M + GRID_M / 2, x1, GRID_M)
        ys = np.arange(math.floor(y0 / GRID_M) * GRID_M + GRID_M / 2, y1, GRID_M)
        X, Y = np.meshgrid(xs, ys)
        inside = shapely.contains_xy(g, X.ravel(), Y.ravel())
        pts = np.column_stack([X.ravel()[inside], Y.ravel()[inside]])
        if not len(pts):  # smaller than a cell
            c = g.representative_point()
            pts = np.array([[c.x, c.y]])
        b = bus_t.query(pts, distance_upper_bound=BUS_M)[0] <= BUS_M
        r = rail_t.query(pts, distance_upper_bound=RAIL_M)[0] <= RAIL_M
        w = good_t.query(pts, distance_upper_bound=BUS_M)[0] <= BUS_M if good_t else np.zeros(len(pts), bool)
        cov[i] = [b.mean(), r.mean(), (b | r).mean(), w.mean()]

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
            "routes_sum", "bus500", "rail1k", "either", "good500", "route_ok", "osm_fill"]
    rows = []
    for i, d in enumerate(dongs):
        ok = d["sgg"] in route_ok
        rows.append([d["code"], d["name"], d["sido"], d["sidonm"], d["sgg"], d["sggnm"], dong_type(d["name"]), pop[i],
                     round(area[i] / 1e6, 3), int(n_stop[i]), int(n_known[i]), int(n_few[i]), int(sum_rte[i]),
                     round(cov[i, 0], 4), round(cov[i, 1], 4), round(cov[i, 2], 4), round(cov[i, 3], 4) if ok else None,
                     int(ok), int(d["sgg"] in fill)])
    a = area / 1e6
    print(f"coverage (area-weighted): bus {np.sum(cov[:, 0] * a) / a.sum():.1%}, rail {np.sum(cov[:, 1] * a) / a.sum():.1%}, "
          f"either {np.sum(cov[:, 2] * a) / a.sum():.1%}; 동 only bus "
          f"{sum(cov[i, 0] * a[i] for i, d in enumerate(dongs) if dong_type(d['name']) == '동') / sum(a[i] for i, d in enumerate(dongs) if dong_type(d['name']) == '동'):.1%}",
          flush=True)

    trips, tmonths, tlost = load_trips(dongs)
    print(f"trips: {len(trips)} 시군구 (months {', '.join(tmonths) or '-'}), "
          f"{sum('transfer' in v for v in trips.values())} with 환승; not mapped: {', '.join(tlost) or '-'}", flush=True)
    sgg_trips = {g: {"day": round(v["modes"]["day"], 1), "modes": {m: round(x, 1) for m, x in v["modes"]["by_mode"].items()},
                     "users": {u: round(x, 1) for u, x in v["modes"]["by_user"].items()},
                     "transfer": round(v["transfer"]["day"], 1) if "transfer" in v else None}
                 for g, v in trips.items() if "modes" in v}
    meta = {"boundary": adm["ver"], "trips_months": tmonths, "pop_ym": pop_raw["ym"], "stops_collected": sm["collected"], "route_days": rdays,
            "n_stops": int(len(s_lon)), "n_osm_added": int(add.sum()), "n_stations": len(stations),
            "bus_m": BUS_M, "rail_m": RAIL_M, "grid_m": GRID_M, "good_routes": GOOD_ROUTES}
    with open(os.path.join(OUT, "stats.json"), "w", encoding="utf-8") as f:
        json.dump({"meta": meta, "cols": cols, "rows": rows, "sgg_trips": sgg_trips}, f, ensure_ascii=False, separators=(",", ":"))
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
                    "노선수자료있음", "OSM정류장보완"])
        w.writerows(rows)
    for name in ("stats.json", "dongs.geojson", "stops.json", "stations.json"):
        print(f"  {name}: {os.path.getsize(os.path.join(OUT, name)) / 1e6:.1f} MB", flush=True)


if __name__ == "__main__":
    main()
