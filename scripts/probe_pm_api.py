"""Temporary probe: what 국토교통부 (TAGO) 공유 퍼스널모빌리티정보 (apis.data.go.kr/1613000/PersonalMobilityInfo) returns.
Reads the swagger embedded in the data.go.kr page, then calls each path; the key is never printed."""
import os
import re

import requests

KEY = os.environ["DATA_GO_KR_KEY"]
BASE = "https://apis.data.go.kr/1613000/PersonalMobilityInfo"
UA = {"User-Agent": "korea-transit-gap probe"}


def clean(t):
    return t.replace(KEY, "***").replace(requests.utils.quote(KEY, safe=""), "***")


t = requests.get("https://www.data.go.kr/data/15117668/openapi.do", timeout=60, headers=UA).text
paths = sorted(set(re.findall(r'"(/[A-Za-z]\w+)":\{"get"', t)))
print("paths:", paths, flush=True)
for m in re.finditer(r'"oprtinUrl":"([^"]+)","oprtinNm":"([^"]+)"', t):
    print("operation:", m.group(1), "|", m.group(2), flush=True)
for m in re.finditer(r'\{"paramtrNm":"(\w+)","paramtrDc":"([^"]*)","paramtrBassValue":"([^"]*)","paramtrTy":"\w*","paramtrDivision":"([^"]*)"', t):
    print("  param:", m.groups(), flush=True)
for m in re.finditer(r'"(\w+)":\{"type":"\w+","description":"([^"]{1,40})"\}', t):
    print("  field:", m.groups(), flush=True)

for p in paths + ["/getPMListByProvider", "/GetPMListByProvider"]:
    for extra in ({}, {"cityCode": "25"}, {"cityCode": "25", "providerName": "빔"}):
        r = requests.get(BASE + p, params={"serviceKey": KEY, "_type": "json", "numOfRows": 5, "pageNo": 1, **extra}, timeout=60, headers=UA)
        print(f"-- {p} {extra}: HTTP {r.status_code}: {re.sub(r'\\s+', ' ', clean(r.text))[:700]}", flush=True)
