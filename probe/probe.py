"""Temporary: 성·연령별 주민등록 인구 APIs (법정동 stdg…, 행정동 admm…). Deleted after use."""
import json
import os
import re

import requests

KEY = os.environ.get("DATA_GO_KR_KEY", "")
H = {"User-Agent": "Mozilla/5.0"}
for name in ("stdgSexdAgePpltn", "admmSexdAgePpltn"):
    print(f"\n== {name}", flush=True)
    page = requests.get("https://www.data.go.kr/tcs/dss/selectDataSetList.do", headers=H, timeout=60, params={"keyword": "성별 연령별 주민등록 인구", "dType": "API"}).text
    for pk in list(dict.fromkeys(re.findall(r"/data/(\d+)/openapi\.do", page)))[:8]:
        doc = requests.get(f"https://www.data.go.kr/data/{pk}/openapi.do", headers=H, timeout=60).text
        m = re.search(r"const swaggerJson = `(.*?)`;", doc, re.S)
        if m and name in m.group(1):
            sw = json.loads(m.group(1))
            for path, ops in sw["paths"].items():
                op = ops.get("get") or next(iter(ops.values()))
                print("  page", pk, path, [(q["name"], q.get("required"), (q.get("description") or "")[:30]) for q in op.get("parameters", [])])
            break
    for path in ("/select" + name[0].upper() + name[1:], ""):
        for lv in (3, 2):
            p = {"serviceKey": KEY, "type": "JSON", "numOfRows": 3, "pageNo": 1, "srchFrYm": "202609", "srchToYm": "202609", "lv": lv,
                 "regSeCd": 1, "admmCd": "1111000000", "stdgCd": "1111000000"}
            try:
                r = requests.get(f"https://apis.data.go.kr/1741000/{name}{path}", params=p, timeout=60)
                print(f"  {path} lv{lv}: {r.status_code} {' '.join(r.text.split())[:1300]}", flush=True)
            except Exception as e:  # noqa: BLE001
                print("  FAILED", repr(e)[:150])
