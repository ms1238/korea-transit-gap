"""Temporary: check which sources answer from GitHub Actions. Deleted after one run."""
import csv
import io
import os
import re
from collections import Counter

import requests

KEY = os.environ.get("DATA_GO_KR_KEY", "")
H = {"User-Agent": "Mozilla/5.0"}


def show(title, f):
    print(f"\n== {title}", flush=True)
    try:
        f()
    except Exception as e:  # noqa: BLE001
        print("  FAILED:", repr(e)[:300], flush=True)


def bus_file():
    """국토교통부_전국 버스정류장 위치정보 (fileData 15067528): metadata, then the file itself."""
    r = requests.get("https://www.data.go.kr/catalog/15067528/fileData.json", headers=H, timeout=60)
    print("  catalog json", r.status_code, r.text[:2500])
    page = requests.get("https://www.data.go.kr/data/15067528/fileData.do", headers=H, timeout=60).text
    for line in page.splitlines():
        if re.search(r"atchFile|fileDetailSn|fileDataDown|수정일|주기|\.csv|\.xlsx|\.zip", line):
            print("  page:", re.sub(r"\s+", " ", line.strip())[:300])
    ids = re.findall(r"FILE_\d+", page)
    if not ids:
        return
    f = requests.get("https://www.data.go.kr/cmm/cmm/fileDownload.do", params={"atchFileId": ids[0], "fileDetailSn": 1},
                     headers={**H, "Referer": "https://www.data.go.kr/data/15067528/fileData.do"}, timeout=300)
    print("  download", ids[0], f.status_code, f.headers.get("Content-Type"), f.headers.get("Content-Disposition"), len(f.content), "bytes")
    for enc in ("utf-8-sig", "cp949"):
        try:
            text = f.content.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        print("  not text; first bytes", f.content[:20])
        return
    rows = list(csv.DictReader(io.StringIO(text)))
    print("  columns", list(rows[0]) if rows else None, "rows", len(rows))
    print("  first rows", rows[:2])
    for col in rows[0] if rows else []:
        if re.search("도시|지자체|시군|관리", col):
            c = Counter(r[col] for r in rows)
            print(f"  {col}: {len(c)} values", c.most_common(400))


def tago_api():
    r = requests.get("https://apis.data.go.kr/1613000/BusSttnInfoInqireService/getCtyCodeList",
                     params={"serviceKey": KEY, "_type": "json"}, timeout=60)
    print("  ", r.status_code, r.text[:1500])


def osm_count():
    q = """[out:json][timeout:180];
area["ISO3166-1"="KR"][admin_level=2]->.k;
node["highway"="bus_stop"](area.k);
out count;"""
    for url in ("https://overpass-api.de/api/interpreter", "https://overpass.private.coffee/api/interpreter"):
        try:
            r = requests.post(url, data={"data": q}, timeout=(15, 240), headers={"User-Agent": "korea-transit-gap"})
            print("  ", url, r.status_code, r.text[:500])
            if r.status_code == 200:
                return
        except Exception as e:  # noqa: BLE001
            print("  ", url, repr(e)[:200])


def dong_population():
    """행정동 (lv 3) population: one city 구 and one 군."""
    for admm in ("1111000000", "4783000000"):
        r = requests.get("https://apis.data.go.kr/1741000/admmPpltnHhStus/selectAdmmPpltnHhStus", timeout=60,
                         params={"serviceKey": KEY, "admmCd": admm, "srchFrYm": "202609", "srchToYm": "202609", "lv": 3,
                                 "regSeCd": 1, "type": "JSON", "numOfRows": 100, "pageNo": 1})
        print("  ", admm, r.status_code, r.text[:1200])


def reach(url):
    r = requests.get(url, headers=H, timeout=(15, 60))
    print("  ", url, r.status_code, len(r.content), "bytes")


show("bus stop file", bus_file)
show("TAGO bus stop API", tago_api)
show("OSM bus_stop count", osm_count)
show("행정동 population (lv 3)", dong_population)
show("도로명주소 business.juso.go.kr", lambda: reach("https://business.juso.go.kr/"))
show("SGIS", lambda: reach("https://sgis.kostat.go.kr/"))
