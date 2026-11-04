"""Temporary probe: coverage of 국토교통부 (TAGO) 공유 퍼스널모빌리티정보 (apis.data.go.kr/1613000/PersonalMobilityInfo):
every provider (GetPMProvider) and its device count (GetPMListByProvider totalCount). The key is never printed."""
import os
import re

import requests

KEY = os.environ["DATA_GO_KR_KEY"]
BASE = "https://apis.data.go.kr/1613000/PersonalMobilityInfo"
UA = {"User-Agent": "korea-transit-gap probe"}


def call(op, **params):
    r = requests.get(f"{BASE}/{op}", params={"serviceKey": KEY, "_type": "json", **params}, timeout=60, headers=UA)
    return r.json()["response"]


p = call("GetPMProvider", numOfRows=1000, pageNo=1)
items = p["body"]["items"]
items = items["item"] if items else []
items = items if isinstance(items, list) else [items]
print("providers:", p["body"]["totalCount"], items, flush=True)
for it in items:
    b = call("GetPMListByProvider", cityCode=it["citycode"], providerName=it["providername"], numOfRows=3, pageNo=1)["body"]
    sample = b["items"]["item"] if b.get("items") else []
    sample = sample if isinstance(sample, list) else [sample]
    print(f"  {it['cityname']} {it['providername']}: {b['totalCount']} devices; sample "
          + str([{k: v for k, v in s.items() if k != 'vehicleid'} for s in sample[:2]]), flush=True)
