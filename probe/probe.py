"""Temporary: what the odcloud datasets 15080989 / 15085874 and 상가정보 (sdsc2) return. Deleted after use."""
import json
import os

import requests

KEY = os.environ.get("DATA_GO_KR_KEY", "")
for ns in ("15080989", "15085874"):
    print(f"\n== odcloud {ns}", flush=True)
    try:
        spec = requests.get(f"https://infuser.odcloud.kr/oas/docs?namespace={ns}/v1", timeout=60).json()
        print("  title:", spec["info"].get("title"))
        paths = sorted(spec["paths"], key=lambda p: spec["paths"][p]["get"].get("summary", ""))
        for p in paths[-3:]:
            print("  table:", p, spec["paths"][p]["get"].get("summary", ""))
        d = requests.get("https://api.odcloud.kr/api" + paths[-1], params={"serviceKey": KEY, "page": 1, "perPage": 3, "returnType": "JSON"}, timeout=90)
        print("  latest:", d.status_code, " ".join(d.text.split())[:1200])
    except Exception as e:  # noqa: BLE001
        print("  FAILED", repr(e)[:200])
print("\n== sdsc2", flush=True)
B = "https://apis.data.go.kr/B553077/api/open/sdsc2"
for op, p in [("storeListInDong", {"divId": "adongCd", "key": "1111053000"}), ("storeListInDong", {"divId": "signguCd", "key": "47830"}),
              ("storeListInRadius", {"radius": 500, "cx": 127.0276, "cy": 37.4979}), ("largeUpjongList", {}), ("baroApi", {"resId": "dong", "catId": "mega"})]:
    try:
        r = requests.get(f"{B}/{op}", params={"serviceKey": KEY, "pageNo": 1, "numOfRows": 3, "type": "json", **p}, timeout=(15, 120))
        print(f"  {op} {p}: {r.status_code} {" ".join(r.text.split())[:900]}", flush=True)
    except Exception as e:  # noqa: BLE001
        print(f"  {op}: FAILED {repr(e)[:150]}")
