"""Temporary: STCIS (교통카드 빅데이터 통합정보시스템) open API, key from the BIGDATA secret. Deleted after use."""
import os

import requests

KEY = os.environ.get("BIGDATA", "")
print("key set:", bool(KEY))
BASE = "https://stcis.go.kr/openapi/"


def call(name, **params):
    for attempt in range(2):
        try:
            r = requests.get(BASE + name, params={"apikey": KEY, **params}, timeout=(15, 120), headers={"User-Agent": "Mozilla/5.0"})
            body = r.text.replace("\n", " ")
            print(f"  {name} {params}: {r.status_code} len={len(body)} {body[:900]}", flush=True)
            return
        except Exception as e:  # noqa: BLE001
            print(f"  {name} {params}: try {attempt + 1} {repr(e)[:150]}", flush=True)


print("\n== 지역코드")
call("areacode.json")
call("areacode.json", sdCd="51")
call("areacode.json", sdCd="51", sggCd="51150")
call("areacode.json", sdCd="42")
print("\n== 버스 정류장 (강릉, 고령, 광주 서구)")
call("bussttn.json", sdCd="51", sggCd="51150")
call("bussttn.json", sdCd="51", sggCd="51150", emdCd="5115010100")
call("bussttn.json", sdCd="47", sggCd="47830")
call("bussttn.json", sdCd="29", sggCd="29140")
print("\n== 버스 노선")
call("busroute.json", sdCd="51", routeNo="202")
call("busroute.json", sdCd="51")
print("\n== 노선별 경유정류장")
call("busroutesttn.json", sdCd="51", sggCd="51150", emdCd="5115010100")
print("\n== 도시철도")
call("rlrdroute.json")
call("rlrdroutesttn.json", routeNm="광주1호선")
print("\n== 15분 OD")
call("quarterod.json", opratDate="20250801", stgEmdCd="5115010100", arrEmdCd="5115010200")
