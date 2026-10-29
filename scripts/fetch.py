"""Download the sources of the transit-gap dashboard into raw/.

- admin_dong:   행정동 boundaries (vuski/admdongkor, from 통계청 boundaries; follows 2026 reorganizations)
- dong_pop:     주민등록 인구 per 행정동 (행정안전부, latest published month)
- stops_molit:  국토교통부 전국 버스정류장 위치정보 (yearly file; only 지자체 whose BIS is linked to TAGO)
- stops_osm:    bus stops from OpenStreetMap (fills 시군구 missing from the 국토부 file)
- stations_osm: railway stations and halts from OpenStreetMap (도시철도, 광역·일반철도, KTX)
- routes:       국토교통부 정류장별 정차 노선수 (교통카드 data), one 시군구 per file under raw/routes/
- age_dong:     행정안전부 행정동 기준 성·연령별 주민등록 인구 (20–39 and 70+ per 행정동)
- age:          행정안전부 법정동 기준 성·연령별 주민등록 인구, summed per 시군구
- lh:           한국토지주택공사 전국 LH아파트 단지정보 (odcloud)
- stores:       소상공인시장진흥공단 상가(상권)정보 points per 시군구 under raw/stores/
- trips:        국토교통부 교통수단별 이용량 and 환승 이용량 (교통카드 data, monthly), summed per 시군구 under raw/trips/
                These APIs are slow, so each run fetches what fits in API_BUDGET_MIN and later runs continue.

`--only-missing` fetches only sources that have no file in raw/ yet (code pushes reuse the cached data);
routes, stores and trips always continue within their budget.

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
API_BUDGET_MIN = 55  # 정차 노선수 and trip volumes together, per run; the job limit is 90 minutes
DEADLINE = [0.0]
STORES_MAX_DAYS = 90  # 상가 data is quarterly
TRIPS = {  # kind -> (monthly operation, mode field or None)
    "modes": ("https://apis.data.go.kr/1613000/TransportationModeTripVolume/getMonthlyTransportationModeTripVolume", "trfc_mns_nm"),
    "transfer": ("https://apis.data.go.kr/1613000/TransferTripVolume/getMonthlyTransferTripVolume", None),
}
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
STORES = "https://apis.data.go.kr/B553077/api/open/sdsc2/storeListInDong"  # 소상공인시장진흥공단 상가(상권)정보
AGE = "https://apis.data.go.kr/1741000/stdgSexdAgePpltn/selectStdgSexdAgePpltn"  # 법정동 기준 성·연령별 주민등록 인구
AGE_DONG = "https://apis.data.go.kr/1741000/admmSexdAgePpltn/selectAdmmSexdAgePpltn"  # 행정동 기준 성·연령별 주민등록 인구
LH_SPEC = "https://infuser.odcloud.kr/oas/docs?namespace=15080989/v1"  # 한국토지주택공사 전국 LH아파트 단지정보
SOURCES = ["admin_dong", "dong_pop", "age", "age_dong", "stops_molit", "stops_osm", "stations_osm", "lh", "routes", "stores", "trips"]
OPTIONAL = {"age", "age_dong", "lh", "routes", "stores", "trips"}  # the page is built without them (their figures stay empty)
FRESH_DAYS = {"admin_dong": 7, "dong_pop": 7, "stops_molit": 30, "stops_osm": 7, "stations_osm": 7, "lh": 30, "age": 7, "age_dong": 7}  # refetch after this many days


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
        if d["head"]["resultCode"] == "3":  # NODATA_ERROR: this code has no rows at this level
            return [], 0
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
    out = {r["admmCd"]: int(r["totNmprCnt"]) for r in dongs if r.get("dongNm")}  # a 시 and its 구 can both list a 행정동
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


def api_call(url, params, what):
    """One page of a 1613000 (교통카드) API; (totalCount, items), totalCount 0 when the API has no data."""
    for attempt in range(3):
        try:
            d = requests.get(url, timeout=(15, 180), params=params).json()
            if "Response" not in d and "Error" not in d:  # e.g. the gateway's SERVICETIMEOUT_ERROR
                raise RuntimeError(str(d)[:200])
            break
        except Exception as e:  # noqa: BLE001
            err = e
            time.sleep(10)
    else:
        raise RuntimeError(f"{what}: {err}")
    if "Error" in d:
        if d["Error"].get("code") == "50":  # NO_DATA_FOUND
            return 0, []
        raise RuntimeError(f"{what}: {d['Error']}")
    body = d["Response"]["body"]
    items = (body.get("items") or {}).get("item") or []
    return int(body.get("totalCount") or 0), ([items] if isinstance(items, dict) else items)


def routes_call(key, day, ctpv, sgg, page, rows=1000):
    return api_call(ROUTES, {"serviceKey": key, "pageNo": page, "numOfRows": rows, "dataType": "JSON", "opr_ymd": day,
                             "ctpv_cd": ctpv, "sgg_cd": sgg}, f"{day} {sgg} page {page}")


def every_page(call):
    """All rows of a paged call(page) -> (total, items)."""
    total, rows = call(1)
    rows, page = list(rows), 1
    while len(rows) < total:
        page += 1
        got = call(page)[1]
        if not got:
            break
        rows += got
    return rows


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
        for attempt in range(5):  # STCIS often drops the connection; it answers on a retry
            try:
                d = requests.get(STCIS_AREAS, params={"apikey": stcis, "sdCd": sd}, headers={"User-Agent": "Mozilla/5.0"}, timeout=(15, 120)).json()
                break
            except Exception as e:  # noqa: BLE001
                err = e
                time.sleep(10 * (attempt + 1))
        else:
            raise RuntimeError(f"STCIS 지역코드 {sd}: {err}")
        cands += [(sd, r["sggCd"], r["sggNm"]) for r in d.get("result") or [] if r.get("sggCd")]
    def has_data(sd, sgg):
        try:
            return routes_call(key, day, sd, sgg, 1, 1)[0] > 0
        except RuntimeError as e:
            print(f"  routes {sgg}: {e}", flush=True)
            return False
    areas = [[sd, sgg, name] for sd, sgg, name in dict.fromkeys(cands) if has_data(sd, sgg)]
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
    done = 0
    for ctpv, sgg, name in todo:
        if time.time() > DEADLINE[0]:
            break
        try:
            rows = every_page(lambda page: routes_call(key, day, ctpv, sgg, page))
        except RuntimeError as e:  # a slow 시군구 waits for the next run
            print(f"  routes {sgg}: {e}", flush=True)
            continue
        stops = {}
        for r in rows:
            stops[r["sttn_id"]] = [r["sttn_id"], r["sttn_nm"] or "", r["emd_cd"] or "", max(r["rte_cnt"] or 0, stops.get(r["sttn_id"], [0, 0, 0, 0])[3])]
        save_json(os.path.join("routes", day, f"{ctpv}_{sgg}.json"), {"ctpv_nm": rows[0]["ctpv_nm"] if rows else "",
                                                                      "sgg_nm": rows[0]["sgg_nm"] if rows else name, "stops": list(stops.values())})
        done += 1
    left = len(todo) - done
    print(f"routes: {day}, {len(areas)} 시군구, fetched {done} this run, {left} left", flush=True)


def fetch_age(key):
    """주민등록 인구 by 10-year age band per 시군구 (lv 2 rows of each 시도) for the latest published month:
    {ym, rows: [{code, sido, sgg, tot, ages: {0: n, 10: n, …, 100: n}}]} (male and female summed)."""
    def call(sido, ym):
        p = {"serviceKey": key, "type": "JSON", "numOfRows": 100, "pageNo": 1, "srchFrYm": ym, "srchToYm": ym, "lv": 2, "regSeCd": 1,
             "stdgCd": sido + "00000000"}
        d = requests.get(AGE, params=p, timeout=60).json()["Response"]
        if d["head"]["resultCode"] == "3":
            return []
        if d["head"]["resultCode"] != "0":
            raise RuntimeError(f"{sido} {ym}: {d['head']}")
        items = (d.get("items") or {}).get("item") or []
        return [items] if isinstance(items, dict) else items
    today = date.today()
    for k in range(1, 4):
        ym = "%d%02d" % (today.year - (today.month - k <= 0), (today.month - k - 1) % 12 + 1)
        if call("11", ym):
            break
    else:
        raise RuntimeError("no month in the last three has data")
    rows = []
    for sido in STCIS_SIDO:
        for r in call(sido, ym):
            ages = {a: int(r.get(f"male{a}AgeNmprCnt") or 0) + int(r.get(f"feml{a}AgeNmprCnt") or 0) for a in range(0, 101, 10)}
            rows.append({"code": r["stdgCd"], "sido": r["ctpvNm"], "sgg": r["sggNm"], "tot": int(r["totNmprCnt"]), "ages": ages})
    print(f"age: {ym}, {len(rows)} 시군구 rows, population {sum(r['tot'] for r in rows):,}", flush=True)
    if len(rows) < 200:
        raise RuntimeError(f"only {len(rows)} rows")
    save_json("age.json", {"ym": ym, "rows": rows})


def fetch_age_dong(key):
    """주민등록 인구 by 10-year age band per 행정동 (lv 3; through the 시군구 where a 시도 code lists none) for the latest
    month: {ym, dongs: {admmCd: [total, 20–39, 70+]}}."""
    def call(admm, ym, lv, page=1):
        p = {"serviceKey": key, "type": "JSON", "numOfRows": 100, "pageNo": page, "srchFrYm": ym, "srchToYm": ym, "lv": lv,
             "regSeCd": 1, "admmCd": admm}
        for attempt in range(4):
            try:
                d = requests.get(AGE_DONG, params=p, timeout=60).json()
                if "Response" not in d:  # e.g. an unregistered key: the gateway's own error, not worth retrying
                    raise RuntimeError(f"{admm} {ym} lv{lv}: {str(d)[:200]}")
                d = d["Response"]
                break
            except RuntimeError:
                raise
            except Exception as e:  # noqa: BLE001
                err = e
                time.sleep(5 + attempt * 5)
        else:
            raise RuntimeError(f"{admm} {ym} lv{lv}: {err}")
        if d["head"]["resultCode"] == "3":
            return [], 0
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
    for k in range(1, 4):
        ym = "%d%02d" % (today.year - (today.month - k <= 0), (today.month - k - 1) % 12 + 1)
        sido, _ = call("1100000000", ym, 1)
        if sido:
            break
    else:
        raise RuntimeError("no month in the last three has data")
    n = lambda r, a: int(r.get(f"male{a}AgeNmprCnt") or 0) + int(r.get(f"feml{a}AgeNmprCnt") or 0)
    out = {}
    for s in sido:
        rows = every(s["admmCd"], ym, 3)
        if not rows:
            for g in every(s["admmCd"], ym, 2):
                rows += every(g["admmCd"], ym, 3)
        for r in rows:
            if r.get("dongNm"):
                out[r["admmCd"]] = [int(r["totNmprCnt"]), n(r, 20) + n(r, 30), sum(n(r, a) for a in (70, 80, 90, 100))]
    print(f"age_dong: {ym}, {len(out)} 행정동", flush=True)
    if len(out) < 3000:
        raise RuntimeError(f"only {len(out)} 행정동")
    save_json("age_dong.json", {"ym": ym, "dongs": out})


def fetch_lh(key):
    """LH 아파트 단지 (the latest odcloud table): [[단지명, 세대수, 임대유형, 주택유형, 주소], …]; 주소 is often empty."""
    spec = requests.get(LH_SPEC, timeout=60).json()
    path = max(spec["paths"], key=lambda q: spec["paths"][q]["get"].get("summary", "")[-8:])
    rows, page = [], 1
    while True:
        d = requests.get("https://api.odcloud.kr/api" + path, params={"serviceKey": key, "page": page, "perPage": 1000, "returnType": "JSON"}, timeout=120).json()
        if "data" not in d:
            raise RuntimeError(str(d)[:200])
        rows += [[r.get("단지명") or "", r.get("세대수") or 0, r.get("임대유형") or "", r.get("주택유형") or "", r.get("주소") or ""] for r in d["data"]]
        if page * 1000 >= d.get("totalCount", 0):
            break
        page += 1
    title = spec["paths"][path]["get"].get("summary", "")
    print(f"lh: {title}: {len(rows)} 단지, {sum(1 for r in rows if r[4])} with an address", flush=True)
    save_json("lh.json", {"table": title, "rows": rows})


def fetch_stores(key):
    """상가업소 per current 시군구 (sdsc2 storeListInDong by signguCd): raw/stores/<sgg>.json = {ym, stores: [[lon, lat,
    업종대분류코드], …]}. Continues within the shared budget; a 시군구 older than STORES_MAX_DAYS is fetched again."""
    sggs = sorted({d["sgg"] for d in json.load(open(os.path.join(RAW, "admin_dong.json"), encoding="utf-8"))["dongs"]})
    folder = os.path.join(RAW, "stores")
    os.makedirs(folder, exist_ok=True)
    old = lambda s: not os.path.exists(os.path.join(folder, f"{s}.json")) or time.time() - os.path.getmtime(os.path.join(folder, f"{s}.json")) > STORES_MAX_DAYS * 86400
    todo, done = [s for s in sggs if old(s)], 0
    for sgg in todo:
        if time.time() > DEADLINE[0]:
            break
        out, ym, page = [], "", 1
        try:
            while True:
                for attempt in range(3):
                    try:
                        d = requests.get(STORES, params={"serviceKey": key, "divId": "signguCd", "key": sgg, "numOfRows": 1000, "pageNo": page, "type": "json"},
                                         timeout=(15, 120)).json()
                        break
                    except Exception as e:  # noqa: BLE001
                        err = e
                        time.sleep(10)
                else:
                    raise RuntimeError(f"stores {sgg} page {page}: {err}")
                h = d.get("header", {})
                if h.get("resultCode") == "03":  # NODATA
                    break
                if h.get("resultCode") != "00":
                    raise RuntimeError(f"stores {sgg}: {h}")
                ym = h.get("stdrYm", ym)
                items = (d.get("body") or {}).get("items") or []
                out += [[round(float(i["lon"]), 6), round(float(i["lat"]), 6), i.get("indsLclsCd", "")] for i in items if i.get("lon") and i.get("lat")]
                if len(items) < 1000:
                    break
                page += 1
        except RuntimeError as e:
            print(f"  {e}", flush=True)
            continue
        save_json(os.path.join("stores", f"{sgg}.json"), {"ym": ym, "stores": out})
        done += 1
    print(f"stores: {len(sggs)} 시군구, fetched {done} this run, {len(todo) - done} left", flush=True)


def trips_month(key):
    """The latest month the trip-volume API has data for."""
    first = date.today().replace(day=1)
    for k in range(1, 13):
        ym = (first - timedelta(days=28 * k - 1)).strftime("%Y%m")
        if api_call(TRIPS["modes"][0], {"serviceKey": key, "pageNo": 1, "numOfRows": 1, "dataType": "JSON", "opr_ym": ym,
                                        "ctpv_cd": ROUTES_PROBE[0], "sgg_cd": ROUTES_PROBE[1]}, ym)[0]:
            return ym
    raise RuntimeError("no month in the last year has data")


def fetch_trips(key):
    """Monthly 교통카드 trips per 시군구 (국토교통부 교통수단별 이용량, 환승 이용량), summed over 법정동 and hours:
    raw/trips/<ym>/<kind>_<ctpv>_<sgg>.json = {sgg_nm, ocrn, arvl, by_mode {mode: [ocrn, arvl]}, by_user {type: ocrn}}
    (ocrn = 출발·승차 통행, arvl = 도착 통행). Runs after routes, whose 시군구 list it reuses, within the same budget."""
    days = sorted(d for d in os.listdir(os.path.join(RAW, "routes")) if os.path.exists(os.path.join(RAW, "routes", d, "areas.json")))
    if not days:
        raise RuntimeError("no 시군구 list yet (routes)")
    areas = json.load(open(os.path.join(RAW, "routes", days[-1], "areas.json"), encoding="utf-8"))
    ym = trips_month(key)
    folder = os.path.join(RAW, "trips", ym)
    todo = [(k, a) for k in TRIPS for a in areas if not os.path.exists(os.path.join(folder, f"{k}_{a[0]}_{a[1]}.json"))]
    done = 0
    for kind, (ctpv, sgg, name) in todo:
        if time.time() > DEADLINE[0]:
            break
        url, mode_field = TRIPS[kind]
        try:
            rows = every_page(lambda page: api_call(url, {"serviceKey": key, "pageNo": page, "numOfRows": 1000, "dataType": "JSON",
                                                          "opr_ym": ym, "ctpv_cd": ctpv, "sgg_cd": sgg}, f"{kind} {ym} {sgg} page {page}"))
        except RuntimeError as e:
            print(f"  trips {kind} {sgg}: {e}", flush=True)
            continue
        out = {"sgg_nm": rows[0]["sgg_nm"] if rows else name, "ocrn": 0, "arvl": 0, "by_mode": {}, "by_user": {}}
        for r in rows:
            o, a = r.get("ocrn_pasg_nope") or 0, r.get("arvl_pasg_nope") or 0
            out["ocrn"] += o
            out["arvl"] += a
            if mode_field:
                m = out["by_mode"].setdefault(r.get(mode_field) or "기타", [0, 0])
                m[0] += o
                m[1] += a
            u = r.get("users_type_nm") or "기타"
            out["by_user"][u] = out["by_user"].get(u, 0) + o
        save_json(os.path.join("trips", ym, f"{kind}_{ctpv}_{sgg}.json"), out)
        done += 1
    print(f"trips: {ym}, {len(areas)} 시군구 x {len(TRIPS)}, fetched {done} this run, {len(todo) - done} left", flush=True)


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
        path = os.path.join(RAW, name if name in ("routes", "trips", "stores") else name + ".json")
        have = os.path.exists(path)
        if have and name in FRESH_DAYS and (only_missing or time.time() - os.path.getmtime(path) < FRESH_DAYS[name] * 86400):
            continue
        if name == "routes":  # the slow APIs share one budget, counted from here
            DEADLINE[0] = time.time() + API_BUDGET_MIN * 60
        try:
            globals()[f"fetch_{name}"](key)
        except Exception as e:  # noqa: BLE001
            print(f"{name}: FAILED {e}" + (" (keeping the last copy)" if have else ""), flush=True)
            if not have and name not in OPTIONAL:
                failed.append(name)
    if failed:
        sys.exit(f"never fetched: {', '.join(failed)}")


if __name__ == "__main__":
    main()
