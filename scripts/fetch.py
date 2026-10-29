"""Download the sources of the transit-gap dashboard into raw/.

- admin_dong:   행정동 boundaries (vuski/admdongkor, from 통계청 boundaries; follows 2026 reorganizations)
- dong_pop:     주민등록 인구 per 행정동 (행정안전부, latest published month)
- stops_molit:  국토교통부 전국 버스정류장 위치정보 (yearly file; only 지자체 whose BIS is linked to TAGO)
- stops_osm:    bus stops from OpenStreetMap (fills 시군구 missing from the 국토부 file)
- stations_osm: railway stations and halts from OpenStreetMap (도시철도, 광역·일반철도, KTX)
- routes:       국토교통부 정류장별 정차 노선수 (교통카드 data), one 시군구 per file under raw/routes/;
                the API is slow, so each run fetches what fits in ROUTES_BUDGET_MIN and later runs continue

`--only-missing` fetches only sources that have no file in raw/ yet (code pushes reuse the cached data);
routes always continue within their budget.

Keys come from the environment (GitHub Actions secrets) and must never be written into the repository:
DATA_GO_KR_KEY (공공데이터포털).
"""
import csv
import io
import json
import math
import os
import re
import sys
import time
from datetime import date, timedelta

import requests

RAW = os.path.join(os.path.dirname(__file__), "..", "raw")
UA = {"User-Agent": "korea-transit-gap (github.com/ms1238/korea-transit-gap)"}
ADMDONG_REPO = "https://api.github.com/repos/vuski/admdongkor/contents"
POPULATION = "https://apis.data.go.kr/1741000/admmPpltnHhStus/selectAdmmPpltnHhStus"
STOPS_PAGE = "https://www.data.go.kr/data/15067528/fileData.do"
ROUTES = "https://apis.data.go.kr/1613000/NumberofRoutesServingEachStop/getNumberofRoutesServingEachStop"
ROUTES_BUDGET_MIN = 45  # per run; the job limit is 90 minutes
ROUTES_PROBE = ("47", "47170")  # 경북 안동시: a 시군구 whose code did not change in the 2026 reorganizations
STCIS_AREAS = "https://stcis.go.kr/openapi/areacode.json"
STCIS_SIDO = ["11", "12", "26", "27", "28", "29", "30", "31", "36", "41", "43", "44", "46", "47", "48", "50", "51", "52"]
OVERPASS = ["https://overpass-api.de/api/interpreter", "https://overpass.private.coffee/api/interpreter",
            "https://maps.mail.ru/osm/tools/overpass/api/interpreter"]
OVERPASS_BUDGET_MIN = 20
_overpass_start = []
BUS_STOPS_QUERY = """[out:json][timeout:240];
area["ISO3166-1"="KR"][admin_level=2]->.k;
node["highway"="bus_stop"](area.k);
out body;"""
STATIONS_QUERY = """[out:json][timeout:240];
area["ISO3166-1"="KR"][admin_level=2]->.k;
nwr["railway"~"^(station|halt)$"](area.k);
out center tags;"""
SOURCES = ["admin_dong", "dong_pop", "stops_molit", "stops_osm", "stations_osm", "routes"]


def save_json(name, data):
    path = os.path.join(RAW, name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path + ".tmp", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(path + ".tmp", path)


def overpass(query):
    """Run an Overpass query on the first mirror that answers; returns the elements."""
    if not _overpass_start:
        _overpass_start.append(time.time())
    deadline = _overpass_start[0] + OVERPASS_BUDGET_MIN * 60
    for url in OVERPASS:
        for attempt in range(2):
            if time.time() > deadline:
                raise RuntimeError(f"Overpass budget ({OVERPASS_BUDGET_MIN} min) spent")
            try:
                r = requests.post(url, data={"data": query}, timeout=(15, 300), headers=UA)
                if r.status_code != 200:
                    raise RuntimeError(f"HTTP {r.status_code}: {r.text[:200]!r}")
                return r.json()["elements"]
            except Exception as e:  # noqa: BLE001
                print(f"  overpass {url} try {attempt + 1}: {e}", flush=True)
                time.sleep(10)
    raise RuntimeError("all Overpass mirrors failed")


def fetch_admin_dong(_key):
    """The latest 행정동 GeoJSON of vuski/admdongkor (one folder per release, verYYYYMMDD), kept as
    [{code, name, sido, sidonm, sgg, sggnm, polys: [[ring, …], …]}] with coordinates rounded to 5 decimals (~1 m)."""
    ver = max(x["name"] for x in requests.get(ADMDONG_REPO, headers=UA, timeout=60).json() if x["type"] == "dir" and x["name"].startswith("ver"))
    files = [x for x in requests.get(f"{ADMDONG_REPO}/{ver}", headers=UA, timeout=60).json() if x["name"].endswith(".geojson")]
    feats = requests.get(files[0]["download_url"], headers=UA, timeout=300).json()["features"]
    out = []
    for f in feats:
        g, p = f["geometry"], f["properties"]
        polys = g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]
        out.append({"code": p["adm_cd2"], "name": p["adm_nm"].split()[-1], "sido": p["sido"], "sidonm": p["sidonm"],
                    "sgg": p["sgg"], "sggnm": p["sggnm"],
                    "polys": [[[[round(x, 5), round(y, 5)] for x, y in ring] for ring in poly] for poly in polys]})
    print(f"admin_dong: {ver}, {len(out)} 행정동", flush=True)
    save_json("admin_dong.json", {"ver": ver, "dongs": out})


def fetch_dong_pop(key):
    """주민등록인구 per 행정동 for the latest published month: lv 3 rows of each 시도 (lv 1 gives the 시도 codes)."""
    def call(admm, ym, lv, page=1):
        params = {"serviceKey": key, "admmCd": admm, "srchFrYm": ym, "srchToYm": ym, "lv": lv, "regSeCd": 1,
                  "type": "JSON", "numOfRows": 100, "pageNo": page}
        for attempt in range(4):
            try:
                d = requests.get(POPULATION, params=params, timeout=60).json()["Response"]
                break
            except Exception as e:  # noqa: BLE001
                err = e
                time.sleep(5 + attempt * 5)
        else:
            raise RuntimeError(f"{admm} {ym} lv{lv}: {err}")
        if d["head"]["resultCode"] != "0":
            raise RuntimeError(f"{admm} {ym} lv{lv}: {d['head']}")
        items = (d.get("items") or {}).get("item") or []
        return ([items] if isinstance(items, dict) else items), int(d["head"]["totalCount"])

    def every(admm, ym, lv):
        rows, page = [], 1
        while True:
            items, total = call(admm, ym, lv, page)
            rows += items
            if len(items) < 100 or page * 100 >= total:
                return rows
            page += 1

    today = date.today()
    for k in range(1, 4):  # published after the month ends
        ym = "%d%02d" % (today.year - (today.month - k <= 0), (today.month - k - 1) % 12 + 1)
        sido, _ = call("1100000000", ym, 1)
        if sido:
            break
    else:
        raise RuntimeError("no month in the last three has data")
    dongs = []
    for s in sido:
        rows = every(s["admmCd"], ym, 3)
        if not rows:  # the 시도 code does not list its 행정동 directly: go through its 시군구
            for g in every(s["admmCd"], ym, 2):
                rows += every(g["admmCd"], ym, 3)
        dongs += rows
    out = {r["admmCd"]: int(r["totNmprCnt"]) for r in dongs if r.get("dongNm")}
    print(f"dong_pop: {ym}, {len(sido)} 시도, {len(out)} 행정동, population {sum(out.values()):,}", flush=True)
    if len(out) < 3000:
        raise RuntimeError(f"only {len(out)} 행정동")
    save_json("dong_pop.json", {"ym": ym, "pop": out})


def fetch_stops_molit(_key):
    """The latest file of 국토교통부_전국 버스정류장 위치정보 (CSV, EUC-KR): [[id, name, lat, lon, city], …]."""
    page = requests.get(STOPS_PAGE, headers={"User-Agent": "Mozilla/5.0"}, timeout=60).text
    m = re.search(r"atchFileId=(FILE_\d+)&(?:amp;)?fileDetailSn=(\d+)", page)
    if not m:
        raise RuntimeError("no download link on the dataset page")
    f = requests.get("https://www.data.go.kr/cmm/cmm/fileDownload.do", params={"atchFileId": m.group(1), "fileDetailSn": m.group(2)},
                     headers={"User-Agent": "Mozilla/5.0", "Referer": STOPS_PAGE}, timeout=300)
    text = f.content.decode("cp949", "replace")
    rows = list(csv.DictReader(io.StringIO(text)))
    out = []
    for r in rows:
        try:
            lat, lon = float(r["위도"]), float(r["경도"])
        except (TypeError, ValueError):
            continue
        if 33 < lat < 39 and 124 < lon < 132:
            out.append([r["정류장번호"], r["정류장명"], round(lat, 6), round(lon, 6), r["도시명"]])
    day = max((r.get("정보수집일") or "" for r in rows), default="")
    print(f"stops_molit: {m.group(1)}, collected {day}, {len(rows)} rows, {len(out)} with coordinates", flush=True)
    if len(out) < 100000:
        raise RuntimeError(f"only {len(out)} stops")
    save_json("stops_molit.json", {"collected": day, "stops": out})


def fetch_stops_osm(_key):
    els = overpass(BUS_STOPS_QUERY)
    out = [[e["id"], e.get("tags", {}).get("name:ko") or e.get("tags", {}).get("name", ""), round(e["lat"], 6), round(e["lon"], 6)]
           for e in els if "lat" in e]
    print(f"stops_osm: {len(out)} bus stops", flush=True)
    if len(out) < 50000:
        raise RuntimeError(f"only {len(out)} stops")
    save_json("stops_osm.json", out)


def fetch_stations_osm(_key):
    out = []
    for e in overpass(STATIONS_QUERY):
        t, c = e.get("tags", {}), e.get("center") or e
        name = t.get("name:ko") or t.get("name") or ""
        if "lat" in c and re.search("[가-힣]", name):
            out.append([name, round(c["lat"], 6), round(c["lon"], 6), t.get("station", ""), t.get("operator", "")])
    print(f"stations_osm: {len(out)} stations", flush=True)
    if len(out) < 500:
        raise RuntimeError(f"only {len(out)} stations")
    save_json("stations_osm.json", out)


def routes_call(key, day, ctpv, sgg, page, rows=1000):
    """One page of 정차 노선수; (totalCount, items), totalCount 0 when the API has no data."""
    for attempt in range(3):
        try:
            d = requests.get(ROUTES, timeout=(15, 180), params={"serviceKey": key, "pageNo": page, "numOfRows": rows,
                                                                "dataType": "JSON", "opr_ymd": day, "ctpv_cd": ctpv, "sgg_cd": sgg}).json()
            break
        except Exception as e:  # noqa: BLE001
            err = e
            time.sleep(10)
    else:
        raise RuntimeError(f"{day} {sgg} page {page}: {err}")
    if "Error" in d:
        if d["Error"].get("code") == "50":  # NO_DATA_FOUND
            return 0, []
        raise RuntimeError(f"{day} {sgg}: {d['Error']}")
    body = d["Response"]["body"]
    items = (body.get("items") or {}).get("item") or []
    return int(body.get("totalCount") or 0), ([items] if isinstance(items, dict) else items)


def routes_day(key):
    """The second Wednesday of the latest month the API has data for (a regular weekday, away from month-end holidays)."""
    first = date.today().replace(day=1)
    for k in range(1, 13):
        m = (first - timedelta(days=28 * k - 1)).replace(day=1)
        wed = m + timedelta(days=(2 - m.weekday()) % 7 + 7)
        if routes_call(key, wed.strftime("%Y%m%d"), *ROUTES_PROBE, 1, 1)[0]:
            return wed.strftime("%Y%m%d")
    raise RuntimeError("no month in the last year has data")


def routes_areas(key, day):
    """[[ctpv, sgg, name], …] the API has data for on `day`. Candidates come from the STCIS 지역코드 API (key BIGDATA),
    which lists old and new codes alike; the API itself still used the pre-2026 codes in mid-2026 (광주 29, 전남 46,
    인천's old 구), so every candidate is tried and the empty ones dropped."""
    stcis = os.environ.get("BIGDATA")
    if not stcis:
        raise RuntimeError("BIGDATA (STCIS key) is not set")
    cands = []
    for sd in STCIS_SIDO:
        d = requests.get(STCIS_AREAS, params={"apikey": stcis, "sdCd": sd}, headers={"User-Agent": "Mozilla/5.0"}, timeout=(15, 120)).json()
        cands += [(sd, r["sggCd"], r["sggNm"]) for r in d.get("result") or [] if r.get("sggCd")]
    areas = [[sd, sgg, name] for sd, sgg, name in dict.fromkeys(cands) if routes_call(key, day, sd, sgg, 1, 1)[0]]
    print(f"routes: {day}, {len(cands)} candidate 시군구 codes, {len(areas)} with data", flush=True)
    if len(areas) < 150:
        raise RuntimeError(f"only {len(areas)} 시군구 with data")
    return areas


def fetch_routes(key):
    """Stops and their route counts per 시군구 for one day: raw/routes/<day>/<ctpv>_<sgg>.json with the unique stops
    [[sttn_id, name, emd_cd, rte_cnt], …] (the API repeats each stop on many rows). The 시군구 list is
    raw/routes/<day>/areas.json (codes as the API has them on that day, which can predate a reorganization)."""
    day = routes_day(key)
    folder = os.path.join(RAW, "routes", day)
    areas_file = os.path.join(folder, "areas.json")
    if not os.path.exists(areas_file):
        save_json(os.path.join("routes", day, "areas.json"), routes_areas(key, day))
    areas = json.load(open(areas_file, encoding="utf-8"))
    todo = [a for a in areas if not os.path.exists(os.path.join(folder, f"{a[0]}_{a[1]}.json"))]
    start, done = time.time(), 0
    for ctpv, sgg, name in todo:
        if time.time() - start > ROUTES_BUDGET_MIN * 60:
            break
        total, items = routes_call(key, day, ctpv, sgg, 1)
        rows, page = list(items), 1
        while len(rows) < total:
            page += 1
            rows += routes_call(key, day, ctpv, sgg, page)[1]
        stops = {}
        for r in rows:
            stops[r["sttn_id"]] = [r["sttn_id"], r["sttn_nm"] or "", r["emd_cd"] or "", max(r["rte_cnt"] or 0, stops.get(r["sttn_id"], [0, 0, 0, 0])[3])]
        save_json(os.path.join("routes", day, f"{ctpv}_{sgg}.json"), {"ctpv_nm": rows[0]["ctpv_nm"] if rows else "",
                                                                      "sgg_nm": rows[0]["sgg_nm"] if rows else name, "stops": list(stops.values())})
        done += 1
    left = len(todo) - done
    print(f"routes: {day}, {len(areas)} 시군구, fetched {done} this run, {left} left", flush=True)


def main():
    """Fetch every source. If one fails and a copy from an earlier run is in raw/ (restored from the Actions cache),
    keep that copy and go on; stop only when a source has never been fetched."""
    key = os.environ.get("DATA_GO_KR_KEY")
    if not key:
        sys.exit("DATA_GO_KR_KEY is not set")
    os.makedirs(RAW, exist_ok=True)
    only_missing = "--only-missing" in sys.argv
    names = [a for a in sys.argv[1:] if not a.startswith("--")] or SOURCES
    failed = []
    for name in names:
        have = os.path.exists(os.path.join(RAW, name if name == "routes" else name + ".json"))
        if only_missing and have and name != "routes":
            continue
        try:
            globals()[f"fetch_{name}"](key)
        except Exception as e:  # noqa: BLE001
            print(f"{name}: FAILED {e}" + (" (keeping the last copy)" if have else ""), flush=True)
            if not have:
                failed.append(name)
    if failed:
        sys.exit(f"never fetched: {', '.join(failed)}")


if __name__ == "__main__":
    main()
