"""Temporary: can TAGO 버스정류소정보 fill 시군구 whose bus stops are missing (속초 etc.)? Never prints the key."""
import os, requests
KEY = os.environ["DATA_GO_KR_KEY"]
red = lambda s: str(s).replace(KEY, "***")
B = "https://apis.data.go.kr/1613000/BusSttnInfoInqireService"
def get(op, **p):
    r = requests.get(f"{B}/{op}", params={"serviceKey": KEY, "_type": "json", "numOfRows": 1000, "pageNo": 1, **p}, timeout=60)
    print(op, p, "HTTP", r.status_code, red(r.text[:300]).replace("\n", " "))
    try: return r.json()["response"]["body"]
    except Exception as e: print("ERR", red(e)); return None
b = get("getCtyCodeList")
items = (b or {}).get("items", {}) or {}
items = items.get("item", []) if isinstance(items, dict) else items
print("cities", len(items))
want = ["속초", "평창", "정선", "화천", "양구", "인제", "증평", "보성", "강진", "영광"]
codes = {}
for x in items:
    n = str(x.get("cityname"))
    if any(w in n for w in want): codes[n] = x.get("citycode")
print("matches", codes)
print("all cities", sorted(str(x.get("cityname")) for x in items))
for n, c in codes.items():
    b = get("getSttnNoList", cityCode=c)
    if b:
        it = b.get("items", {}) or {}; it = it.get("item", []) if isinstance(it, dict) else it
        it = [it] if isinstance(it, dict) else it
        print("STOPS", n, c, "total", b.get("totalCount"), "sample", it[:2])
