"""Temporary: what TransferTripVolume and TransportationModeTripVolume return. Deleted after use."""
import json
import os
import re

import requests

KEY = os.environ.get("DATA_GO_KR_KEY", "")
H = {"User-Agent": "Mozilla/5.0"}


def spec(title, name):
    page = requests.get("https://www.data.go.kr/tcs/dss/selectDataSetList.do", headers=H, timeout=60, params={"keyword": title, "dType": "API"}).text
    for pk in dict.fromkeys(re.findall(r"/data/(\d+)/openapi\.do", page)):
        doc = requests.get(f"https://www.data.go.kr/data/{pk}/openapi.do", headers=H, timeout=60).text
        m = re.search(r"const swaggerJson = `(.*?)`;", doc, re.S)
        if m and name in m.group(1):
            sw = json.loads(m.group(1))
            print("  page", pk, sw.get("host"), "|", sw["info"].get("description", "")[:300])
            return [p for p in sw["paths"]]
    return []


def call(name, path, **p):
    for attempt in range(3):
        try:
            r = requests.get(f"https://apis.data.go.kr/1613000/{name}{path}", timeout=(15, 180),
                             params={"serviceKey": KEY, "pageNo": 1, "numOfRows": 4, "dataType": "JSON", **p})
            return r.status_code, r.text[:1500].replace("\n", " ")
        except Exception as e:  # noqa: BLE001
            err = repr(e)[:100]
    return "ERR", err


for title, name in [("환승 이용량", "TransferTripVolume"), ("교통수단별 이용량", "TransportationModeTripVolume")]:
    print(f"\n== {name}", flush=True)
    paths = spec(title, name) or ["/getDaily" + name, "/getMonthly" + name, "/getAnnual" + name]
    print("  paths", paths, flush=True)
    for path in paths:
        p = {"opr_ymd": "20260610"} if "Daily" in path else {"opr_ym": "202606"} if "Monthly" in path else {"opr_yr": "2025"} if "Annual" in path else {"opr_ymd": "20260610"}
        for ctpv, sgg in [("47", "47170"), ("11", "11140")]:
            print(f"  {path} {p} {sgg}:", *call(name, path, ctpv_cd=ctpv, sgg_cd=sgg, **p), flush=True)
