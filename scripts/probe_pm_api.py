"""Temporary probe: what 국토교통부 (TAGO) 공유 퍼스널모빌리티정보 (apis.data.go.kr/1613000/PersonalMobilityInfo) returns.
Prints the operations from the data.go.kr catalog and a few calls; the key is never printed."""
import json
import os
import re

import requests

KEY = os.environ["DATA_GO_KR_KEY"]
BASE = "https://apis.data.go.kr/1613000/PersonalMobilityInfo"
UA = {"User-Agent": "korea-transit-gap probe"}


def clean(t):
    return t.replace(KEY, "***").replace(requests.utils.quote(KEY, safe=""), "***")


ops = []
for url in ("https://www.data.go.kr/catalog/15117668/openapi.json", "https://www.data.go.kr/data/15117668/openapi.do"):
    try:
        r = requests.get(url, timeout=60, headers=UA)
        print(f"== {url}: HTTP {r.status_code}, {len(r.text)} chars", flush=True)
        if url.endswith(".json"):
            d = r.json()
            print(json.dumps({k: d[k] for k in d if k != "paths"}, ensure_ascii=False)[:1500], flush=True)
            for path, spec in d.get("paths", {}).items():
                for method, op in spec.items():
                    params = [(p.get("name"), p.get("required"), p.get("description", "")[:60]) for p in op.get("parameters", [])]
                    print(f"  {method.upper()} {path}: {op.get('summary', '')} | params {params}", flush=True)
                    ops.append(path)
        else:
            for m in sorted(set(re.findall(r"/PersonalMobilityInfo/(\w+)", r.text))):
                print("  op in page:", m, flush=True)
                ops.append("/" + m)
            for m in re.findall(r"(?:갱신주기|업데이트 주기|제공기관|비용부과|트래픽)[^<]{0,80}", r.text)[:10]:
                print("  ", m.strip(), flush=True)
    except Exception as e:  # noqa: BLE001
        print(f"== {url}: {e}", flush=True)

for op in sorted(set(ops)) or ["/getPMProviderList", "/getPMListByProvider", "/getCtyCodeList"]:
    for extra in ({}, {"cityCode": "25"}):
        try:
            r = requests.get(BASE + op, params={"serviceKey": KEY, "_type": "json", "numOfRows": 10, "pageNo": 1, **extra}, timeout=60, headers=UA)
            print(f"-- {op} {extra}: HTTP {r.status_code}: {clean(r.text)[:1200]}", flush=True)
        except Exception as e:  # noqa: BLE001
            print(f"-- {op} {extra}: {e}", flush=True)
