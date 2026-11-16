"""Temporary: download 전국자전거도로표준데이터 to probe/bike_road.csv.gz for a local analysis. Never prints the key."""
import csv, gzip, os, requests
KEY = os.environ["DATA_GO_KR_KEY"]
URL = "https://api.data.go.kr/openapi/tn_pubr_public_bike_road_api"
F = ["rteNm", "ctpvNm", "sggNm", "roadStPointRoadNmAddr", "roadEdPointRoadNmAddr", "roadStPointLat", "roadStPointLon", "roadEdPointLat",
     "roadEdPointLon", "majorStopover", "totalLength", "bikeRoadWidth", "bikeRoadType", "bikeRoadNotiChk", "mngInstNm", "crtrYmd"]
rows, n, total = [], 1, None
while total is None or len(rows) < total:
    d = requests.get(URL, params={"serviceKey": KEY, "pageNo": n, "numOfRows": 1000, "type": "json"}, timeout=(15, 180)).json()
    d = d.get("response", d)
    total = int(d["body"]["totalCount"])
    it = d["body"]["items"]; it = it.get("item", []) if isinstance(it, dict) else it
    if not it: break
    rows += it; n += 1
print("rows", len(rows), "of", total)
with gzip.open("probe/bike_road.csv.gz", "wt", encoding="utf-8", newline="") as f:
    w = csv.writer(f); w.writerow(F)
    for r in rows: w.writerow([r.get(k, "") for k in F])
