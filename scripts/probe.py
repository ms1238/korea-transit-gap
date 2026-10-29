"""Temporary: check which sources answer from GitHub Actions. Deleted after use."""
import json
import os
import re

import requests

KEY = os.environ.get("DATA_GO_KR_KEY", "")
H = {"User-Agent": "Mozilla/5.0"}
print("key set:", bool(KEY))


def show(title, f):
    print(f"\n== {title}", flush=True)
    try:
        f()
    except Exception as e:  # noqa: BLE001
        print("  FAILED:", repr(e)[:300], flush=True)


def molit(pk):
    """Dataset page pk: the swagger embedded in the page (host, basePath, paths, parameters), then one call per path."""
    def f():
        s = requests.Session()
        s.headers.update(H)
        doc = s.get(f"https://www.data.go.kr/data/{pk}/openapi.do", timeout=60).text
        m = re.search(r"const swaggerJson = `(.*?)`;", doc, re.S)
        sw = json.loads(m.group(1))
        print("  host", sw.get("host"), "basePath", sw.get("basePath"), "schemes", sw.get("schemes"))
        for path, ops in sw["paths"].items():
            op = ops.get("get") or next(iter(ops.values()))
            params = [(q["name"], q.get("required"), q.get("description", "")[:60]) for q in op.get("parameters", [])]
            print("  path", path, op.get("summary", ""), params)
            url = f"https://{sw['host']}{sw.get('basePath', '')}{path}"
            args = {"serviceKey": KEY, "pageNo": 1, "numOfRows": 3, "type": "json", "dataType": "JSON", "_type": "json"}
            for q in op.get("parameters", []):
                if q.get("required") and q["name"] not in args:
                    args[q["name"]] = q.get("default") or q.get("example") or ""
            r = s.get(url, params=args, timeout=60)
            print("  call", r.status_code, {k: v for k, v in args.items() if k != "serviceKey"}, r.text[:1200])
    return f


def search(keyword, dtype):
    def f():
        page = requests.get("https://www.data.go.kr/tcs/dss/selectDataSetList.do", headers=H, timeout=60,
                            params={"keyword": keyword, "dType": dtype, "perPage": 40}).text
        for pk, kind in dict.fromkeys(re.findall(r"/data/(\d+)/(openapi|fileData)\.do", page)):
            t = re.search(r'/data/' + pk + r'/' + kind + r'\.do[^>]*>\s*(?:<[^>]+>\s*)*([^<]+)', page)
            print("  ", pk, kind, (t.group(1).strip() if t else "")[:80])
    return f


for pk, title in [("15142067", "정류장별 정차 노선수"), ("15142065", "정류장별 경유노선별 이용량"), ("15142068", "노선별 혼잡도"),
                  ("15142055", "평균통행시간"), ("15142056", "평균통행거리")]:
    show(f"{pk} {title}", molit(pk))
show("search 한국교통안전공단 버스 노선 (file)", search("한국교통안전공단 버스 노선", "FILE"))
show("search 한국교통안전공단 버스 노선 (API)", search("한국교통안전공단 버스 노선", "API"))
show("search 버스 노선별 경유 정류소", search("노선별 경유 정류소", "FILE"))
