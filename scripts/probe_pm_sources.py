"""Temporary probe: what the PM device / parking APIs the user listed return (fields, a sample row, totals).
Keys are never printed."""
import json
import os
import re

import requests

KEY = os.environ["DATA_GO_KR_KEY"]
GG = os.environ.get("GYEONGGI", "")
UA = {"User-Agent": "korea-transit-gap probe"}
ODCLOUD = {
    "15144508": "강원 PM", "15144627": "전북 PM 운영현황", "15144510": "인천 PM 운영현황", "15128228": "천안 PM 주차장",
    "15144678": "경북 PM 대여사업현황", "15144880": "충남 PM 현황", "15118574": "대전 킥보드 주차구역",
    "15142933": "인천 킥보드 주차구역", "15144495": "전남광주 공유킥보드 운영현황", "15142726": "해운대 PM 업체",
    "15142727": "해운대 PM 주차구역", "15127679": "김해 PM 주차구역", "15142692": "부산진 PM 업체", "15142695": "사하 PM 업체",
    "15142694": "부산진 PM 주차구역", "15150556": "도로교통공단 PM 사고 합성", "15142613": "사상 PM 업체",
}


def clean(t):
    for k in (KEY, requests.utils.quote(KEY, safe=""), GG):
        if k:
            t = t.replace(k, "***")
    return re.sub(r"\s+", " ", t)


for ns, name in ODCLOUD.items():
    try:
        spec = requests.get(f"https://infuser.odcloud.kr/oas/docs?namespace={ns}/v1", timeout=60, headers=UA).json()
        paths = list(spec.get("paths", {}))
        print(f"== {ns} {name}: {spec.get('info', {}).get('title')} | {len(paths)} versions", flush=True)
        for p in paths[-3:]:  # the newest versions are usually last
            print("   ", p, "|", spec["paths"][p].get("get", {}).get("summary"), flush=True)
        p = paths[-1]
        r = requests.get("https://api.odcloud.kr/api" + p, params={"serviceKey": KEY, "page": 1, "perPage": 2}, timeout=60, headers=UA)
        d = r.json()
        rows = d.get("data") or []
        print(f"   HTTP {r.status_code} total {d.get('totalCount')} fields {list(rows[0]) if rows else d}", flush=True)
        for row in rows[:2]:
            print("   row:", clean(json.dumps(row, ensure_ascii=False))[:400], flush=True)
    except Exception as e:  # noqa: BLE001
        print(f"== {ns} {name}: {type(e).__name__} {clean(str(e))[:200]}", flush=True)

# data.go.kr REST services: find the dataset page, then the operations in its embedded swagger
for svc, name in (("6300000/kickBoard", "대전 킥보드 주차장"), ("6260000/PmParkingZoneService", "부산 PM 주차구역")):
    try:
        s = requests.get("https://www.data.go.kr/tcs/dss/selectDataSetList.do", params={"keyword": svc.split("/")[1]}, timeout=60, headers=UA).text
        ids = sorted(set(re.findall(r"/data/(\d{8})/openapi\.do", s)))
        print(f"== {name} ({svc}): dataset pages {ids[:5]}", flush=True)
        ops = set()
        for i in ids[:3]:
            t = requests.get(f"https://www.data.go.kr/data/{i}/openapi.do", timeout=60, headers=UA).text
            if svc in t:
                ops |= set(re.findall(r'"(/[A-Za-z]\w+)":\{"get"', t))
                print(f"   page {i}: ops {sorted(ops)}", flush=True)
        for op in sorted(ops) or [""]:
            r = requests.get(f"https://apis.data.go.kr/{svc}{op}", params={"serviceKey": KEY, "pageNo": 1, "numOfRows": 2, "resultType": "json", "_type": "json"}, timeout=60, headers=UA)
            print(f"   {op}: HTTP {r.status_code} {clean(r.text)[:600]}", flush=True)
    except Exception as e:  # noqa: BLE001
        print(f"== {name}: {type(e).__name__} {clean(str(e))[:200]}", flush=True)

print("== 경기도 PM 주차구역: key set" if GG else "== 경기도: no GYEONGGI secret", flush=True)
if GG:
    r = requests.get("https://openapi.gg.go.kr/TBKICKBOARDPARKPLCSTUSM", params={"KEY": GG, "Type": "json", "pIndex": 1, "pSize": 2}, timeout=60, headers=UA)
    print(f"   HTTP {r.status_code} {clean(r.text)[:900]}", flush=True)
