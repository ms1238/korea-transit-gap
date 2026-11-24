import json
s = json.load(open("site/data/stats.json")); c = s["cols"]
rows = [r for r in s["rows"] if r[c.index("sggnm")] == "속초시"]
print("속초 dongs", len(rows), "stops", sum(r[c.index("stops")] for r in rows), "pop", sum(r[c.index("pop")] or 0 for r in rows), "gap", [r[c.index("stop_gap")] for r in rows])
m = json.load(open("raw/stops_molit.json")); o = json.load(open("raw/stops_osm.json"))
box = lambda la, lo: 38.1 < la < 38.25 and 128.45 < lo < 128.62
print("molit in box", sum(1 for s_ in m["stops"] if box(s_[2], s_[3])), "osm in box", sum(1 for s_ in o if box(s_[2], s_[3])))
