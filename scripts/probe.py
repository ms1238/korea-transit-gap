"""Temporary: try the 교통카드 (1613000) APIs with their documented parameters. Deleted after use."""
import os

import requests

KEY = os.environ.get("DATA_GO_KR_KEY", "")
BASE = "https://apis.data.go.kr/1613000"
# (시도, 시군구): 광주 동구 (the documented sample), 서울 중구, 대구 중구, 경북 고령군, 강원 강릉시, 제주시
AREAS = [("29", "29140"), ("11", "11140"), ("27", "27110"), ("47", "47830"), ("51", "51150"), ("50", "50110")]


def call(path, **params):
    try:
        r = requests.get(f"{BASE}/{path}", timeout=60,
                         params={"serviceKey": KEY, "pageNo": 1, "numOfRows": 3, "dataType": "JSON", **params})
        return r.status_code, r.text[:700].replace("\n", " ")
    except Exception as e:  # noqa: BLE001
        return "ERR", repr(e)[:200]


for path, extra in [("NumberofRoutesServingEachStop/getNumberofRoutesServingEachStop", {}),
                    ("StopbyRouteTripVolume/getDailyStopbyRouteTripVolume", {}),
                    ("AverageTravelTime/getAverageTravelTimeforPeoplewithReducedMobility", {})]:
    print(f"\n== {path}", flush=True)
    for day in ("20250801", "20260801"):
        for ctpv, sgg in AREAS:
            for case in ("lower", "upper"):
                p = {"opr_ymd": day, "ctpv_cd": ctpv, "sgg_cd": sgg} if case == "lower" else {"OPR_YMD": day, "CTPV_CD": ctpv, "SGG_CD": sgg}
                print(f"  {day} {sgg} {case}:", *call(path, **p), flush=True)
            if day == "20260801":
                break
    print(f"  monthly?", *call(path.replace("getDaily", "getMonthly"), opr_ym="202509", ctpv_cd="29", sgg_cd="29140"))
