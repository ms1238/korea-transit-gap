"""Temporary: which 시군구 codes 정차 노선수 accepts for 2026, and whether sgg_cd is optional. Deleted after use."""
import os

import requests

KEY = os.environ.get("DATA_GO_KR_KEY", "")
URL = "https://apis.data.go.kr/1613000/NumberofRoutesServingEachStop/getNumberofRoutesServingEachStop"


def call(**p):
    for attempt in range(3):
        try:
            d = requests.get(URL, timeout=(15, 180), params={"serviceKey": KEY, "pageNo": 1, "numOfRows": 2, "dataType": "JSON", **p}).json()
            if "Error" in d:
                return d["Error"]["message"]
            b = d["Response"]["body"]
            it = (b.get("items") or {}).get("item") or []
            return b.get("totalCount"), [(x["ctpv_cd"], x["sgg_cd"], x["sgg_nm"], x["emd_cd"]) for x in it]
        except Exception as e:  # noqa: BLE001
            err = repr(e)[:80]
    return "ERR " + err


for day in ("20260513", "20260610", "20260415"):
    print("==", day, flush=True)
    for ctpv, sgg in [("29", "29140"), ("12", "12240"), ("46", "46110"), ("12", "12110"), ("28", "28110"), ("28", "28125"),
                      ("28", "28260"), ("51", "51150"), ("52", "52110"), ("45", "45110")]:
        print("  ", ctpv, sgg, call(opr_ymd=day, ctpv_cd=ctpv, sgg_cd=sgg), flush=True)
    print("   ctpv only 50:", call(opr_ymd=day, ctpv_cd="50"), flush=True)
    print("   no area:", call(opr_ymd=day), flush=True)
