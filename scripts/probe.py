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


def odcloud(ns):
    """odcloud dataset: list its tables, then call the latest one."""
    def f():
        spec = requests.get(f"https://infuser.odcloud.kr/oas/docs?namespace={ns}", timeout=60).json()
        print("  title:", spec.get("info", {}).get("title"))
        paths = sorted(spec["paths"], key=lambda p: spec["paths"][p]["get"].get("summary", ""))
        for p in paths[-3:]:
            print("  table:", p, spec["paths"][p]["get"].get("summary", ""))
        d = requests.get("https://api.odcloud.kr/api" + paths[-1], params={"serviceKey": KEY, "page": 1, "perPage": 3, "returnType": "JSON"}, timeout=90)
        print("  latest:", d.status_code, d.text[:1500])
    return f


def search(keyword, dtype):
    def f():
        page = requests.get("https://www.data.go.kr/tcs/dss/selectDataSetList.do", headers=H, timeout=60,
                            params={"keyword": keyword, "dType": dtype, "perPage": 40}).text
        for pk, kind in dict.fromkeys(re.findall(r"/data/(\d+)/(openapi|fileData)\.do", page)):
            t = re.search(r'/data/' + pk + r'/' + kind + r'\.do[^>]*>\s*(?:<[^>]+>\s*)*([^<]+)', page)
            print("  ", pk, kind, (t.group(1).strip() if t else "")[:80])
    return f


for ns in ("15150448/v1", "15150455/v1", "15162302/v1", "15144160/v1", "15135605/v1"):
    show(f"odcloud {ns}", odcloud(ns))
show("15142067 정류장별 정차 노선수 (retry)", molit("15142067"))
