"""Temporary: check which sources answer from GitHub Actions. Deleted after use."""
import os
import re

import requests

KEY = os.environ.get("DATA_GO_KR_KEY", "")
H = {"User-Agent": "Mozilla/5.0"}
print("key set:", bool(KEY))


def show(title, f):
    print(f"\n== {title}", flush=True)
    try:
        f()
    except Exception as e:  # noqa: BLE001
        print("  FAILED:", repr(e)[:300], flush=True)


def dong_population():
    """행정동 (lv 3) population: one city 구 and one 군."""
    for admm in ("1111000000", "4783000000"):
        r = requests.get("https://apis.data.go.kr/1741000/admmPpltnHhStus/selectAdmmPpltnHhStus", timeout=60,
                         params={"serviceKey": KEY, "admmCd": admm, "srchFrYm": "202609", "srchToYm": "202609", "lv": 3,
                                 "regSeCd": 1, "type": "JSON", "numOfRows": 100, "pageNo": 1})
        print("  ", admm, r.status_code, r.text[:1000])


def odcloud(ns):
    """odcloud dataset: list its tables, then call the latest one."""
    def f():
        spec = requests.get(f"https://infuser.odcloud.kr/oas/docs?namespace={ns}", timeout=60).json()
        print("  title:", spec.get("info", {}).get("title"), "|", spec.get("info", {}).get("description", "")[:300])
        paths = sorted(spec["paths"], key=lambda p: spec["paths"][p]["get"].get("summary", ""))
        for p in paths:
            print("  table:", p, spec["paths"][p]["get"].get("summary", ""))
        p = paths[-1]
        d = requests.get("https://api.odcloud.kr/api" + p, params={"serviceKey": KEY, "page": 1, "perPage": 3, "returnType": "JSON"}, timeout=90)
        print("  latest:", d.status_code, d.text[:1500])
    return f


def molit(name, title):
    """apis.data.go.kr/1613000/<name>: find the dataset page (operations and parameters), then try them."""
    def f():
        s = requests.Session()
        s.headers.update(H)
        page = s.get("https://www.data.go.kr/tcs/dss/selectDataSetList.do", params={"keyword": title, "dType": "API"}, timeout=60).text
        pks = list(dict.fromkeys(re.findall(r"/data/(\d+)/openapi\.do", page)))
        print("  search hits:", pks[:5])
        for pk in pks[:3]:
            doc = s.get(f"https://www.data.go.kr/data/{pk}/openapi.do", timeout=60).text
            if name not in doc:
                continue
            t = re.search(r"<title>(.*?)</title>", doc, re.S)
            print("  page", pk, t.group(1).strip() if t else "")
            for line in doc.splitlines():
                if re.search(name + r"/\w+|swagger|요청변수|업데이트 주기|수정일|데이터포맷|일일 트래픽", line):
                    print("   ", re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", line)).strip()[:250])
            sw = re.search(r"swaggerUrl\s*[:=]\s*['\"]([^'\"]+)", doc) or re.search(r"(https?://[^'\"]*swagger[^'\"]*)", doc)
            if sw:
                print("  swagger url:", sw.group(1))
                print("  swagger:", s.get(sw.group(1), timeout=60).text[:3000])
            ops = sorted(set(re.findall(name + r"/(\w+)", doc)))
            print("  operations:", ops)
            for op in ops[:4]:
                r = s.get(f"https://apis.data.go.kr/1613000/{name}/{op}", timeout=60,
                          params={"serviceKey": KEY, "pageNo": 1, "numOfRows": 3, "_type": "json", "type": "json"})
                print("  call", op, r.status_code, r.text[:800])
            break
    return f


def juso():
    s = requests.Session()
    s.headers.update(H)
    for u in ("https://business.juso.go.kr/", "https://business.juso.go.kr/addrlink/main.do"):
        r = s.get(u, timeout=60)
        print("  ", u, r.status_code, len(r.text))
        for m in sorted(set(re.findall(r"href=\"([^\"]*(?:[Dd]wld|DB|attrb|elctrn)[^\"]*)\"", r.text)))[:40]:
            print("    link:", m)
        if len(r.text) < 2500:
            print("    body:", r.text[:1500])


show("행정동 population (lv 3)", dong_population)
show("odcloud 15150451 버스 노선 및 시간표", odcloud("15150451/v1"))
show("odcloud 15066795 버스 평균 운행속도", odcloud("15066795/v1"))
show("odcloud 15066799 버스 평균 운행시간", odcloud("15066799/v1"))
for name, title in [("NumberofRoutesServingEachStop", "정류장별 정차 노선수"), ("StopbyRouteTripVolume", "정류장별 경유노선별 이용량"),
                    ("RouteCongestionLevel", "노선별 혼잡도"), ("AverageTravelTime", "평균통행시간"), ("AverageTravelDistance", "평균통행거리")]:
    show(f"{name} ({title})", molit(name, title))
show("도로명주소 건물 DB", juso)
