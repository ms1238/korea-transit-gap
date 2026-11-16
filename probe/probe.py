"""Temporary: what does 전국자전거도로표준데이터 (tn_pubr_public_bike_road_api) return? Never prints the key."""
import collections, json, os, re, sys, requests
KEY = os.environ.get("DATA_GO_KR_KEY", "")
red = lambda s: str(s).replace(KEY, "***") if KEY else str(s)
URLS = ["https://api.data.go.kr/openapi/tn_pubr_public_bike_road_api", "http://api.data.go.kr/openapi/tn_pubr_public_bike_road_api"]

def page(url, n, rows=1000):
    r = requests.get(url, params={"serviceKey": KEY, "pageNo": n, "numOfRows": rows, "type": "json"}, timeout=60)
    return r

items, url = [], None
for u in URLS:
    try:
        r = page(u, 1)
        print("URL", u, "HTTP", r.status_code, "ct", r.headers.get("content-type"))
        print(red(r.text[:600]))
        j = r.json()
        body = j["response"]["body"]; hdr = j["response"]["header"]
        print("header", hdr, "totalCount", body.get("totalCount"))
        it = body["items"]; it = it.get("item", it) if isinstance(it, dict) else it
        items += it; url = u; total = int(body["totalCount"]); break
    except Exception as e:
        print("ERR", u, red(e)); continue
if not url:
    sys.exit(0)
n = 2
while len(items) < total and n < 60:
    try:
        it = page(url, n).json()["response"]["body"]["items"]
        it = it.get("item", it) if isinstance(it, dict) else it
        if not it: break
        items += it
    except Exception as e:
        print("ERR page", n, red(e)); break
    n += 1
print("fetched", len(items), "of", total)
print("FIELDS", list(items[0].keys()))
for x in items[:3]:
    print("SAMPLE", json.dumps(x, ensure_ascii=False))
kt = next((k for k in items[0] if "종류" in k or "Knd" in k or "type" in k.lower()), None)
kl = [k for k in items[0] if "길이" in k or "Lt" in k or "lnth" in k.lower() or "len" in k.lower()]
print("type key", kt, "len keys", kl)
def num(v):
    try: return float(str(v).replace(",", ""))
    except: return 0.0
by = collections.defaultdict(lambda: [0, 0.0])
for x in items:
    t = x.get(kt); by[t][0] += 1; by[t][1] += num(x.get(kl[0])) if kl else 0
for t, (c, L) in sorted(by.items(), key=lambda v: -v[1][1]):
    print("TYPE", t, c, round(L, 1))
# 자전거전용도로 names
dedi = [x for x in items if "전용도로" in str(x.get(kt, ""))]
print("dedicated rows", len(dedi))
for k in items[0]:
    vals = collections.Counter(str(x.get(k))[:30] for x in dedi)
    if len(vals) < 15: print("FIELD", k, dict(vals.most_common(8)))
names = collections.Counter()
for x in dedi:
    for k in items[0]:
        if "명" in k and "기관" not in k and "시도" not in k and "시군구" not in k:
            names[str(x.get(k))[:40]] += 1
print("TOP NAMES", names.most_common(60))
coords = [k for k in items[0] if "위도" in k or "경도" in k or "lat" in k.lower() or "lo" == k.lower()[-2:]]
print("coord keys", coords, "filled", sum(1 for x in items if all(str(x.get(k) or "").strip() for k in coords)))
# Overpass reachable? 국토종주 routes
try:
    q = '[out:json][timeout:60];area["ISO3166-1"="KR"]->.a;relation["route"="bicycle"](area.a);out tags;'
    r = requests.post("https://overpass-api.de/api/interpreter", data={"data": q}, timeout=120)
    rel = r.json()["elements"]
    print("OSM bicycle route relations", len(rel))
    for e in rel:
        t = e.get("tags", {})
        if re.search(r"종주|자전거길|강|천", t.get("name", "")):
            print("ROUTE", e["id"], t.get("name"), t.get("network"), t.get("ref"))
except Exception as e:
    print("overpass ERR", e)
