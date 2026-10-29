"""Temporary: latest date of 정차 노선수, and how many of its stops match the 국토부 stop file by name. Deleted after use."""
import csv
import io
import os
import re
from collections import Counter

import requests

KEY = os.environ.get("DATA_GO_KR_KEY", "")
URL = "https://apis.data.go.kr/1613000/NumberofRoutesServingEachStop/getNumberofRoutesServingEachStop"


def page(day, ctpv, sgg, n=1, rows=1000):
    r = requests.get(URL, timeout=120, params={"serviceKey": KEY, "pageNo": n, "numOfRows": rows, "dataType": "JSON",
                                               "opr_ymd": day, "ctpv_cd": ctpv, "sgg_cd": sgg})
    d = r.json()
    if "Error" in d:
        return d["Error"]["message"], []
    b = d["Response"]["body"]
    items = b["items"]["item"] if b.get("items") else []
    return b.get("totalCount"), items


print("== latest date (광주 서구)")
for day in ["20260901", "20260701", "20260501", "20260301", "20260101", "20251201", "20251101", "20251001", "20250901"]:
    total, _ = page(day, "29", "29140", rows=1)
    print(" ", day, total, flush=True)

print("\n== body keys")
r = requests.get(URL, timeout=120, params={"serviceKey": KEY, "pageNo": 1, "numOfRows": 1, "dataType": "JSON",
                                           "opr_ymd": "20250801", "ctpv_cd": "29", "sgg_cd": "29140"})
print(" ", r.text[-300:])

f = requests.get("https://www.data.go.kr/cmm/cmm/fileDownload.do", params={"atchFileId": "FILE_000000003558143", "fileDetailSn": 1},
                 headers={"User-Agent": "Mozilla/5.0", "Referer": "https://www.data.go.kr/data/15067528/fileData.do"}, timeout=300)
stops = list(csv.DictReader(io.StringIO(f.content.decode("cp949", "replace"))))
norm = lambda s: re.sub(r"[\s.\-·()（）]", "", s or "")

for ctpv, sgg, city in [("29", "29140", "광주광역시"), ("51", "51150", "강원특별자치도 강릉시"), ("47", "47830", "경상북도 고령군"),
                        ("47", "47170", "경상북도 안동시"), ("44", "44825", "충청남도 태안군"), ("41", "41610", "경기도 광주시")]:
    rows, n = [], 1
    while True:
        total, items = page("20250801", ctpv, sgg, n)
        rows += items
        if not items or len(rows) >= int(total if str(total).isdigit() else 0):
            break
        n += 1
    uniq = {(r["sttn_id"], r["sttn_nm"]): r for r in rows}
    named = [r for r in uniq.values() if r["sttn_nm"]]
    names = {norm(s["정류장명"]) for s in stops if s["도시명"] == city}
    hit = [r for r in named if norm(r["sttn_nm"]) in names]
    cnt = Counter(min(r["rte_cnt"] or 0, 5) for r in named)
    print(f"\n== {city} {sgg}: rows {len(rows)} (total {total}), unique stops {len(uniq)}, named {len(named)}, "
          f"국토부 stops in city {sum(s['도시명'] == city for s in stops)}, name match {len(hit)} ({len(hit) / max(len(named), 1):.0%})")
    print("   rte_cnt distribution (5 = 5+):", sorted(cnt.items()))
    print("   unmatched sample:", [r["sttn_nm"] for r in named if r not in hit][:15])
    print("   no-name sample:", [(r["sttn_id"], r["emd_nm"], r["rte_cnt"]) for r in uniq.values() if not r["sttn_nm"]][:5])
