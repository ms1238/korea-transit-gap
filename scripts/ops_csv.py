"""Read which 지방정부 run shared PM and shared bicycles from the maps of the 국토교통부 press release「2025년도
첨단모빌리티 현황조사 결과」(2026-08-21, 참고1, status at the end of 2024) into scripts/static/pm_ops.csv and bike_ops.csv.

The survey publishes no table per 지방정부, only the map, so the map is read:
1. the panel image is taken out of the PDF;
2. the current 시군구 boundaries (raw/admin_dong.json, EPSG:5179) are fitted onto the drawn boundaries: an affine fit,
   then a quadratic warp, both by chamfer matching against the dark boundary lines (mean distance under 1 px);
3. each 시군구 is read as the share of coloured (운영) among coloured and white (미운영) pixels inside it, slightly
   eroded; on the bicycle map the colour also gives the kind (공영 yellow, 민영 blue, 혼합 green);
4. the 시군구 are grouped into the survey's units (161: 특별·광역시 as a whole, a 시 with 구 as a whole, every other
   시·군), each unit operating when most of its pixels are green. 울릉군 sits in an inset box and is read there.
Check: the unit count must match the published 도입률 (공유 PM 73.3% = 118 of 161, 공유자전거 51.0% = 82 of 161). The
same reading of the car-sharing panel gives 122 of 161 = 75.8%, also as published.

Run once per survey (needs pymupdf and pyproj, and raw/admin_dong.json):
    python scripts/ops_csv.py press.pdf pm
    python scripts/ops_csv.py press.pdf bike [check.png]
"""
import csv
import json
import os
import sys
from collections import defaultdict

import numpy as np
import pymupdf
import pyproj
import shapely
from PIL import Image, ImageDraw
from scipy import ndimage, optimize

ROOT = os.path.join(os.path.dirname(__file__), "..")
METRO = {"11", "26", "27", "28", "30", "31", "36"}  # 특별·광역시 and 세종 (광주 is inside 12 since 2026, see unit())
KINDS = {  # image on page 7 of the press release, published count of operating units, output file
# inset: x0, y0, x1, y1 of the 울릉·독도 box; legend: it sits right of x and below y
    "pm": {"image": 2, "expected": 118, "out": "pm_ops.csv", "inset": (750, 90, 868, 186), "legend": (580, 900)},
    "bike": {"image": 1, "expected": 82, "out": "bike_ops.csv", "inset": (745, 95, 880, 205), "legend": (590, 830)},
}


def panel(pdf, page, k):
    d = pymupdf.open(pdf)
    xref = d[page].get_images(full=True)[k][0]
    import io
    return np.asarray(Image.open(io.BytesIO(d.extract_image(xref)["image"])).convert("RGB")).astype(int)


def unit(sido, sidonm, name):
    """The survey unit of a current 시군구."""
    if sido in METRO:
        return sidonm
    if sido == "12" and name.endswith("구"):  # the former 광주광역시
        return "광주광역시"
    if "시" in name[:-1] and name.endswith("구"):
        return name[:name.index("시") + 1]
    return f"{sidonm} {name}"


def main():
    pdf, kind = sys.argv[1], sys.argv[2]
    cfg = KINDS[kind]
    img = panel(pdf, 6, cfg["image"])
    INSET, LEGEND = cfg["inset"], cfg["legend"]
    H, W, _ = img.shape
    dark = img.max(axis=2) < 100
    dark[INSET[1]:INSET[3], INSET[0]:INSET[2]] = False
    dark[LEGEND[1]:, LEGEND[0]:] = False
    dt = ndimage.distance_transform_edt(~dark)
    green = (img.max(axis=2) - img.min(axis=2) > 60) & (img.max(axis=2) > 100)  # any fill colour: operating
    white = img.min(axis=2) > 200
    R, G, Bl = img[..., 0], img[..., 1], img[..., 2]
    hue = {"공영": green & (R > 170) & (Bl < 110), "민영": green & (Bl > R + 60), "혼합": green & (G > R + 40) & (G > Bl + 30)}

    with open(os.path.join(ROOT, "raw", "admin_dong.json"), encoding="utf-8") as f:
        dongs = json.load(f)["dongs"]
    parts, info = defaultdict(list), {}
    for d in dongs:
        parts[d["sgg"]].append(shapely.MultiPolygon([(p[0], p[1:]) for p in d["polys"]]).buffer(0))
        info[d["sgg"]] = (d["sido"], d["sidonm"], d["sggnm"])
    tr = pyproj.Transformer.from_crs(4326, 5179, always_xy=True)
    to5179 = lambda g: shapely.transform(g, lambda xy: np.column_stack(tr.transform(xy[:, 0], xy[:, 1])))
    sgg = {g: to5179(shapely.union_all(ps).buffer(0)) for g, ps in parts.items()}
    ulleung = [g for g in sgg if info[g][2] == "울릉군"]

    # boundary points to match: no 울릉 (inset), no islets
    pts = []
    for g, u in sgg.items():
        if g in ulleung:
            continue
        big = [q for q in shapely.get_parts(u) if q.area > 2e6]
        u = shapely.MultiPolygon(big) if big else u
        pts.append(shapely.get_coordinates(shapely.segmentize(u.boundary, 1000)))
    P = np.vstack(pts)
    X0, Y0 = P[:, 0].mean(), P[:, 1].mean()
    x, y = (P[:, 0] - X0) / 1e5, (P[:, 1] - Y0) / 1e5
    B = np.column_stack([np.ones_like(x), x, y, x ** 2, x * y, y ** 2])

    def cost(q, cap):
        u, v = B @ q[:6], B @ q[6:]
        ok = (u >= 0) & (u < W - 1) & (v >= 0) & (v < H - 1)
        c = np.full(len(u), float(cap))
        c[ok] = np.minimum(dt[v[ok].astype(int), u[ok].astype(int)], cap)
        return c.mean()

    # start: the bounding boxes of the lines and of the data, then affine, then quadratic
    ys, xs = np.where(dark)
    sx = (np.percentile(xs, 99.5) - np.percentile(xs, 0.5)) / (np.percentile(x, 99.5) - np.percentile(x, 0.5))
    sy = (np.percentile(ys, 99.5) - np.percentile(ys, 0.5)) / (np.percentile(y, 99.5) - np.percentile(y, 0.5))
    q = np.zeros(12)
    q[:3] = [np.percentile(xs, 0.5) - sx * np.percentile(x, 0.5), sx, 0]
    q[6:9] = [np.percentile(ys, 99.5) + sy * np.percentile(y, 0.5), 0, -sy]
    for free, caps in (([0, 1, 2, 6, 7, 8], (40, 20)), (list(range(12)), (20, 10, 6, 4))):
        sc = np.array([5, 3, 3, 2, 2, 2] * 2, float)
        for cap in caps:
            for _ in range(2):
                def f(z):
                    qq = q.copy()
                    qq[free] += z * sc[free]
                    return cost(qq, cap)
                r = optimize.minimize(f, np.zeros(len(free)), method="Powell", options={"maxiter": 20000, "xtol": 1e-3, "ftol": 1e-5})
                q[free] += r.x * sc[free]
            sc /= 2
    print(f"fit: mean distance to the drawn boundaries {cost(q, 40):.2f} px", flush=True)

    def warp(c):
        xx, yy = (c[:, 0] - X0) / 1e5, (c[:, 1] - Y0) / 1e5
        b = np.column_stack([np.ones_like(xx), xx, yy, xx ** 2, xx * yy, yy ** 2])
        return list(zip(b @ q[:6], b @ q[6:]))

    if len(sys.argv) > 3:  # check image: the fitted boundaries in red over the map
        im = Image.fromarray(img.astype(np.uint8))
        dr = ImageDraw.Draw(im)
        for u in sgg.values():
            for poly in shapely.get_parts(u):
                dr.line(warp(shapely.get_coordinates(poly.exterior)), fill=(230, 30, 30), width=1)
        im.save(sys.argv[3])
    units = defaultdict(lambda: [0, 0, []])
    kinds = defaultdict(lambda: defaultdict(int))
    for g, u in sgg.items():
        if g in ulleung:
            box = (slice(INSET[1] + 6, INSET[3] - 6), slice(INSET[0] + 6, INSET[2] - 6))  # inside the frame
            gn, wh = int(green[box].sum()), 0 if green[box].sum() else 1
        else:
            m = Image.new("L", (W, H), 0)
            dr = ImageDraw.Draw(m)
            for poly in shapely.get_parts(u):
                dr.polygon(warp(shapely.get_coordinates(poly.exterior)), fill=1)
            m = np.asarray(m).astype(bool)
            e = ndimage.binary_erosion(m, iterations=3)
            mm = e if (e & (green | white)).sum() >= 15 else m
            gn, wh = int((mm & green).sum()), int((mm & white).sum())
        k_ = unit(*info[g])
        if g not in ulleung:
            for h, msk in hue.items():
                kinds[k_][h] += int((mm & msk).sum())
        units[k_][0] += gn
        units[k_][1] += wh
        units[k_][2].append(g)
    share = {k_: v[0] / max(v[0] + v[1], 1) for k_, v in units.items()}
    n_on = sum(s > 0.5 for s in share.values())
    unclear = sorted(k_ for k_, s in share.items() if 0.2 < s < 0.8)
    print(f"units {len(units)}, operating {n_on} ({n_on / len(units):.1%}); unclear: {', '.join(unclear) or '-'}", flush=True)
    if n_on != cfg["expected"] or len(units) != 161:
        print(f"WARNING: expected {cfg['expected']} of 161", flush=True)
    kind_of = {k_: (max(v, key=v.get) if kind == "bike" and share[k_] > 0.5 and sum(v.values()) else "") for k_, v in
               ((k_, kinds[k_]) for k_ in units)}
    if kind == "bike":
        print("kinds: " + ", ".join(f"{h} {sum(1 for x in kind_of.values() if x == h)}" for h in hue), flush=True)

    out = os.path.join(os.path.dirname(__file__), "static", cfg["out"])
    with open(out, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["시군구코드", "시도", "시군구", "조사단위", "운영", "판독비율", "유형", "기준", "출처"])
        for k_, (gn, wh, gs) in sorted(units.items()):
            for g in sorted(gs):
                w.writerow([g, info[g][1], info[g][2], k_, int(share[k_] > 0.5), round(share[k_], 3), kind_of[k_], "2024-12-31",
                            "국토교통부 2025년도 첨단모빌리티 현황조사 결과(2026-08-21) 참고1 지도 판독"])
    print(f"wrote {out}", flush=True)


if __name__ == "__main__":
    main()
