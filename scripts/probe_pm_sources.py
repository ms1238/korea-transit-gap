"""Temporary probe: distinct values of the 도로교통공단 PM 교통사고 합성데이터 (odcloud 15150556). Keys are never printed."""
import collections
import os

import requests

KEY = os.environ["DATA_GO_KR_KEY"]
UA = {"User-Agent": "korea-transit-gap probe"}
spec = requests.get("https://infuser.odcloud.kr/oas/docs?namespace=15150556/v1", timeout=60, headers=UA).json()
for p, v in spec["paths"].items():
    print("version:", p, v["get"].get("summary"), flush=True)
path = list(spec["paths"])[-1]
rows, page = [], 1
while True:
    d = requests.get("https://api.odcloud.kr/api" + path, params={"serviceKey": KEY, "page": page, "perPage": 1000}, timeout=120, headers=UA).json()
    rows += d["data"]
    if len(rows) >= d["totalCount"] or not d["data"]:
        break
    page += 1
print("rows", len(rows), "totalCount", d["totalCount"], flush=True)
for k in rows[0]:
    c = collections.Counter(r[k] for r in rows)
    if k == "발생지역":
        sido = collections.Counter(str(x).split("-")[0] for x in c.elements())
        print("시도:", dict(sido), flush=True)
        print("발생지역", len(c), ":", " | ".join(f"{x}" for x in sorted(c)), flush=True)
    else:
        print(k, len(c), ":", dict(sorted(c.items(), key=lambda x: str(x[0]))) if len(c) < 40 else list(c.most_common(10)), flush=True)
print("sums:", {k: sum(r[k] for r in rows) for k in ("사망자수", "중상자수", "경상자수", "부상신고자수")}, flush=True)
