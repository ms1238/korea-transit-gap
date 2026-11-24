"""속초 가상주차제 PM 10분권 분석 + 구상도. Inputs: geo/lc.npz (ESA WorldCover 2021), geo/sokcho.geojson (vuski/admdongkor ver20261001)."""
import json, os, sys
import numpy as np, shapely
from shapely.geometry import shape, LineString, Point, Polygon
from shapely.ops import transform as stf
from rasterio import Affine
from rasterio.features import rasterize, shapes
from scipy import ndimage
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.colors import ListedColormap
from matplotlib.patches import Patch
from matplotlib.lines import Line2D

D = os.path.dirname(os.path.abspath(__file__))
OUT = sys.argv[1]
for f in ("NotoSansKR-Regular.otf", "NotoSansKR-Bold.otf"):
    font_manager.fontManager.addfont(os.path.join(D, "fonts", f))
plt.rcParams["font.family"] = "Noto Sans KR"

LAT0, LON0 = 38.2, 128.59
KX, KY = 111320 * np.cos(np.radians(LAT0)), 110950
to_m = lambda lon, lat: ((np.asarray(lon) - LON0) * KX, (np.asarray(lat) - LAT0) * KY)
to_ll = lambda x, y: (np.asarray(x) / KX + LON0, np.asarray(y) / KY + LAT0)
M = lambda g: stf(lambda x, y, z=None: to_m(x, y), g)
LL = lambda g: stf(lambda x, y, z=None: to_ll(x, y), g)

d = np.load(os.path.join(D, "geo", "lc.npz")); lc = d["a"]; T = Affine(*d["t"])
PX = (T.a * KX) * (-T.e * KY)  # m2 per pixel
feats = json.load(open(os.path.join(D, "geo", "sokcho.geojson")))["features"]
dongs = [(f["properties"]["adm_nm"].split()[-1], shape(f["geometry"])) for f in feats]
city = shapely.union_all([g for _, g in dongs])
cityM = M(city)
inside = rasterize([(city, 1)], out_shape=lc.shape, transform=T) == 1
built = (lc == 50) & inside

# --- lakes (WorldCover water inside the city)
lab, n = ndimage.label((lc == 80) & inside)
sz = ndimage.sum(np.ones_like(lab), lab, range(1, n + 1))
def lake(rank):
    i = np.argsort(sz)[::-1][rank] + 1
    polys = [shape(g) for g, v in shapes((lab == i).astype(np.uint8), mask=lab == i, transform=T) if v == 1]
    return M(max(polys, key=lambda p: p.area)).simplify(15)
yeongnang, cheongcho = lake(0), lake(1)  # 영랑호 1.0km2 (north), 청초호 0.86km2

# --- coastline: easternmost land pixel per row (sea = water/no-data east of it); piers/breakwaters removed by an opening
LAND = ndimage.binary_opening(~np.isin(lc, (0, 80)), structure=np.ones((13, 13)))
def coast(lat_a, lat_b, inset=40):
    pts = []
    for lat in np.arange(lat_a, lat_b, 0.0002):
        r = int((lat - T.f) / T.e)
        c0, c1 = int((128.585 - T.c) / T.a), int((128.62 - T.c) / T.a)
        land = np.where(LAND[r, c0:c1])[0]
        if len(land):
            lon = T.c + (c0 + land.max() + 0.5) * T.a
            x, y = to_m(lon, lat); pts.append((float(x) - inset, float(y)))
    pts = np.array(pts)
    pts[:, 0] = ndimage.uniform_filter1d(ndimage.median_filter(pts[:, 0], 15), 7)
    return LineString(pts).simplify(10)

ring = lambda p, b=25: LineString(p.buffer(b).exterior.coords)
P = lambda lat, lon: Point(*map(float, to_m(lon, lat)))
# phase 1 = 고속버스터미널·속초해수욕장 → 청호동 해안길 → 아바이마을 + 청초호 둘레 + 엑스포공원~터미널 연결
coast1 = coast(38.1850, 38.2040)
lakeR = ring(cheongcho)
term = P(38.19051, 128.59873)  # 속초고속버스터미널 (국토부 터미널 현황 좌표)
expo = Point(lakeR.interpolate(lakeR.project(P(38.19162, 128.5831))).coords[0])  # 엑스포타워 (TourAPI)
lk0 = Point(lakeR.interpolate(lakeR.project(P(38.1915, 128.5895))).coords[0])
link = LineString([lk0.coords[0], term.coords[0], coast1.interpolate(coast1.project(term)).coords[0]])
phase1 = [("청호동·속초해수욕장 해안길", coast1), ("청초호 둘레", lakeR), ("엑스포공원–고속버스터미널", link)]
# phase 2 = 설악대교 북측 해안(속초항·동명항·영금정) → 영랑호 둘레
coast2 = coast(38.2040, 38.2185)
phase2 = [("동명항·영금정 해안길", coast2), ("영랑호 둘레", ring(yeongnang))]

# --- 입지 점수(50m 격자): 반경 300m 내 영업 숙박시설 수(가중 0.4) + 관광지(TourAPI, 0.3) + 버스정류장(OSM, 0.3), 각 p95에서 상한
gd = np.load(os.path.join(D, "grid.npz"))
GX, GY = gd["X"], gd["Y"]; Lp, Tp, Bp = gd["Lp"], gd["Tp"], gd["Bp"]
Bp = np.array([b for b in Bp if cityM.contains(Point(*b))])  # 속초시 경계 안 정류장만
SC = 0.4 * np.minimum(gd["cL"] / 15, 1) + 0.3 * np.minimum(gd["cT"] / 4, 1) + 0.3 * np.minimum(gd["cB"] / 6, 1)
GT = Affine(50, 0, GX[0, 0] - 25, 0, 50, GY[0, 0] - 25)
def grade_poly(th):
    return shapely.union_all([shape(g) for g, v in shapes((SC >= th).astype(np.uint8), mask=(SC >= th), transform=GT) if v == 1]).intersection(cityM)
ZA, ZB = 0.6, 0.35
zoneU = grade_poly(ZA).buffer(30).buffer(-30)
zoneB = grade_poly(ZB)
TER = {"고속버스터미널": P(38.19051, 128.59873), "시외버스터미널": P(38.21118, 128.59088)}

def spots(lines):
    out = []
    for _, ln in lines:
        s = 0.0
        while s <= ln.length:
            p = ln.interpolate(s); a = zoneU.distance(p) <= 60; out.append((p, a))
            s += 75 if a else 175
    # drop near-duplicates where lines meet
    keep = []
    for p, a in out:
        if all(p.distance(q) > 40 for q, _ in keep):
            keep.append((p, a))
    return keep

sp1 = spots(phase1); sp2 = spots(phase2)

# --- 숙박시설형·관광지형 거점: 회랑 도보권(300m) 안의 관광지와 호텔급 숙박시설 중, 100m 안에 회랑 구역이 없는 곳에 1개씩 추가
LM = json.load(open(os.path.join(D, "lodging", "meta.json"))); LR = json.load(open(os.path.join(D, "lodging", "pts.json")))["rows"]
TRS = json.load(open(os.path.join(D, "lodging", "tour.json")))
HOTEL = {"관광호텔업", "가족호텔업", "소형호텔업", "호스텔업", "휴양콘도미니엄업", "일반호텔", "의료관광호텔업", "수상관광호텔업", "한국전통호텔업"}
lodg = [(Point(*map(float, to_m(r[1], r[0]))), LM["types"][r[2]]["name"], r[9]) for r in LR if r[3] == 4 and r[6] == 0 and r[13] != 1 and r[0] and r[1]]
tours = [(Point(*map(float, to_m(r[1], r[0]))), LM["tour"]["types"][r[2]], r[4]) for r in TRS if r[3] == 4 and r[0] and r[1]]
def point_spots(lines, base_spots):
    corr = shapely.union_all([ln for _, ln in lines]); have = [p for p, _ in base_spots]; tour_s, lodge_s = [], []
    for pt, kind, nm in tours:
        if corr.distance(pt) <= WALK and min(pt.distance(q) for q in have) > 100:
            tour_s.append((pt, nm)); have.append(pt)
    for pt, kind, nm in lodg:
        if kind in HOTEL and corr.distance(pt) <= WALK and min(pt.distance(q) for q in have) > 100:
            lodge_s.append((pt, nm)); have.append(pt)
    return tour_s, lodge_s
WALK = 300
pt1_tour, pt1_lodge = point_spots(phase1, sp1)
pt2_tour, pt2_lodge = point_spots(phase1 + phase2, sp1 + sp2 + [(p, 0) for p, _ in pt1_tour + pt1_lodge])
def reach(spts, r=WALK):
    ps = [p for p in spts]
    near = lambda q: min(q.distance(x) for x in ps) <= r
    return dict(lodg=sum(near(q) for q, _, _ in lodg), hotel=sum(near(q) for q, k, _ in lodg if k in HOTEL), tour=sum(near(q) for q, _, _ in tours),
                stops=sum(near(Point(*b)) for b in Bp))
all1 = [p for p, _ in sp1] + [p for p, _ in pt1_tour + pt1_lodge]
all12 = all1 + [p for p, _ in sp2] + [p for p, _ in pt2_tour + pt2_lodge]

WALK, PM5, PM10 = 300, 770, 1540  # 직선거리(m): 도보 5분(80m/분, 우회계수 1.3), PM 12km/h 5분·10분(우회계수 1.3)
def cover(lines):
    base = shapely.union_all([ln for _, ln in lines])
    res = {}
    for k, r in (("walk", WALK), ("pm5", PM5), ("pm10", PM10)):
        g = base.buffer(r).intersection(cityM)
        m = rasterize([(LL(g), 1)], out_shape=lc.shape, transform=T) == 1
        res[k] = dict(geom=g, area=g.area / 1e6, built=(built & m).sum() * PX / 1e6, mask=m)
    return res

c1 = cover(phase1); c12 = cover(phase1 + phase2)
city_km2 = inside.sum() * PX / 1e6; built_km2 = built.sum() * PX / 1e6
stats = dict(city_km2=city_km2, built_km2=built_km2,
             lc={k: float(((lc == c) & inside).sum() * PX / 1e6) for k, c in (("forest", 10), ("grass", 30), ("crop", 40), ("built", 50), ("bare", 60), ("water", 80))},
             lengths={nm: ln.length for nm, ln in phase1 + phase2},
             spots1=dict(total=len(sp1), A=sum(a for _, a in sp1), tour=len(pt1_tour), lodge=len(pt1_lodge)), spots2=dict(total=len(sp2), A=sum(a for _, a in sp2), tour=len(pt2_tour), lodge=len(pt2_lodge)),
             base=dict(lodg=len(lodg), hotel=sum(k in HOTEL for _, k, _ in lodg), tour=len(tours), stops=len(Bp)),
             reach1=reach(all1), reach12=reach(all12), reach1_pm10=reach(all1, PM10), reach12_pm10=reach(all12, PM10),
             pt_names=dict(tour1=[n for _, n in pt1_tour], lodge1=[n for _, n in pt1_lodge], tour2=[n for _, n in pt2_tour], lodge2=[n for _, n in pt2_lodge]))
for tag, c in (("p1", c1), ("p12", c12)):
    stats[tag] = {k: dict(area=v["area"], area_pct=v["area"] / city_km2 * 100, built=v["built"], built_pct=v["built"] / built_km2 * 100) for k, v in c.items()}
stats["dong"] = []
for nm, g in dongs:
    m = rasterize([(g, 1)], out_shape=lc.shape, transform=T) == 1
    b = (built & m).sum() * PX / 1e6
    stats["dong"].append(dict(name=nm, area=M(g).area / 1e6, built=b,
                              p1_pm10=(built & m & c1["pm10"]["mask"]).sum() * PX / 1e6 / b * 100 if b else 0,
                              p12_pm10=(built & m & c12["pm10"]["mask"]).sum() * PX / 1e6 / b * 100 if b else 0,
                              p1_walk=(built & m & c1["walk"]["mask"]).sum() * PX / 1e6 / b * 100 if b else 0))
json.dump(stats, open(os.path.join(OUT, "stats.json"), "w"), ensure_ascii=False, indent=1)

# ---------- maps
cmap = ListedColormap(["#ffffff", "#cfe3c4", "#e9efd6", "#f1ecd2", "#9a9a9a", "#e6e0d2", "#a9cbe6"])
idx = np.zeros(lc.shape, np.uint8)
for i, c in enumerate((10, 30, 40, 50, 60), start=1):
    idx[lc == c] = i
idx[(lc == 80) | (lc == 0)] = 6; idx[(lc == 90)] = 6
H, W = lc.shape
x0, y0 = to_m(T.c, T.f); x1, y1 = to_m(T.c + W * T.a, T.f + H * T.e)
ext = (x0, x1, y1, y0)

def base(ax, xl, yl, bnd=True):
    ax.imshow(idx, cmap=cmap, vmin=0, vmax=6, extent=ext, interpolation="nearest")
    if bnd:
        for nm, g in dongs:
            for poly in (M(g).geoms if g.geom_type == "MultiPolygon" else [M(g)]):
                ax.plot(*poly.exterior.xy, color="#6b6b6b", lw=0.6, ls=(0, (3, 2)))
    ax.set_xlim(*xl); ax.set_ylim(*yl); ax.set_aspect("equal"); ax.set_xticks([]); ax.set_yticks([])

def fillg(ax, g, **kw):
    for poly in (g.geoms if hasattr(g, "geoms") else [g]):
        if poly.geom_type != "Polygon":
            continue
        ax.fill(*poly.exterior.xy, **kw)

def scalebar(ax, x, y, L=1000):
    ax.plot([x, x + L], [y, y], color="k", lw=2.5); ax.text(x + L / 2, y + 90, f"{L/1000:g}km", ha="center", fontsize=8)

# Figure 1: city-wide coverage
fig, ax = plt.subplots(figsize=(8, 7.6), dpi=200)
bx = cityM.bounds
zx0, zy0 = to_m(128.545, 38.163); zx1, zy1 = to_m(128.625, 38.236)
base(ax, (float(zx0), float(zx1)), (float(zy0), float(zy1)))
fillg(ax, c12["pm10"]["geom"], color="#f2a93b", alpha=0.18, lw=0)
fillg(ax, c1["pm10"]["geom"], color="#e8702a", alpha=0.22, lw=0)
fillg(ax, c1["walk"]["geom"], color="#c0392b", alpha=0.35, lw=0)
for g, col, ls in ((c1["pm10"]["geom"], "#c4561d", "-"), (c12["pm10"]["geom"], "#d08a1c", "--")):
    for poly in (g.geoms if hasattr(g, "geoms") else [g]):
        if poly.geom_type == "Polygon":
            ax.plot(*poly.exterior.xy, color=col, lw=1.1, ls=ls)
for _, ln in phase1:
    ax.plot(*ln.xy, color="#8e1b10", lw=2)
for _, ln in phase2:
    ax.plot(*ln.xy, color="#8e1b10", lw=1.6, ls=(0, (2, 1.5)))
for nm, g in dongs:
    c = M(g).representative_point() if nm not in ("대포동", "노학동") else None
    if nm == "대포동": c = Point(*map(float, to_m(128.592, 38.170)))
    if nm == "노학동": c = Point(*map(float, to_m(128.560, 38.197)))
    ax.text(c.x, c.y, nm, fontsize=8, color="#333", ha="center", alpha=.85, clip_on=True)
ax.text(*map(float, to_m(128.5465, 38.180)), "← 서쪽: 설악산 국립공원 일대(산림)\n시 면적의 71%, PM 대상 아님", fontsize=7.5, color="#3d6b35", ha="left")
scalebar(ax, float(zx0) + 300, float(zy0) + 300, 1000)
ax.legend(handles=[Patch(color="#c0392b", alpha=.5, label=f"도보 5분권 (가상주차 회랑 ±{WALK}m)"),
                   Patch(color="#e8702a", alpha=.4, label=f"1단계 PM 10분권 (±{PM10/1000:.2f}km)"),
                   Patch(color="#f2a93b", alpha=.3, label="2단계 확대 시 PM 10분권"),
                   Line2D([], [], color="#8e1b10", lw=2, label="1단계 가상주차 회랑"),
                   Line2D([], [], color="#8e1b10", lw=1.6, ls=":", label="2단계 회랑"),
                   Patch(color="#9a9a9a", label="시가지(건물지, WorldCover)"),
                   Patch(color="#cfe3c4", label="산림")], loc="upper left", fontsize=7.5, frameon=True)
ax.set_title("속초 동부 시가지: 가상주차 회랑 기반 도보·PM 10분권", fontsize=12, weight="bold")
fig.tight_layout(); fig.savefig(os.path.join(OUT, "map_coverage.png")); plt.close(fig)

# Figure 2: concept map of the pilot corridor
fig, ax = plt.subplots(figsize=(8, 9.2), dpi=220)
cx0, cy0 = to_m(128.5745, 38.1835); cx1, cy1 = to_m(128.6115, 38.2205)
base(ax, (cx0, cx1), (cy0, cy1), bnd=False)
fillg(ax, zoneB, color="#f5b041", alpha=0.10, lw=0)
for g in getattr(zoneU, "geoms", [zoneU]):
    if g.geom_type == "Polygon":
        fillg(ax, g, color="#e74c3c", alpha=0.16, lw=0); ax.plot(*g.exterior.xy, color="#e74c3c", lw=0.9, ls="--")
ax.scatter(Lp[:, 0], Lp[:, 1], s=4, c="#7d3c98", alpha=.55, lw=0, zorder=4)
ax.scatter(Bp[:, 0], Bp[:, 1], s=7, marker="s", c="#555", alpha=.7, lw=0, zorder=4)
ax.scatter(Tp[:, 0], Tp[:, 1], s=16, marker="^", c="#1e8449", alpha=.85, lw=0, zorder=4)
for _, ln in phase1:
    ax.plot(*ln.xy, color="#2c6fb7", lw=3, alpha=.8, solid_capstyle="round")
for _, ln in phase2:
    ax.plot(*ln.xy, color="#2c6fb7", lw=2, alpha=.6, ls=(0, (2, 1.5)))
for p, a in sp1:
    ax.plot(p.x, p.y, "o", ms=5.2 if a else 4.4, mfc="#e74c3c" if a else "#1f4e8c", mec="white", mew=.7, zorder=5)
for p, a in sp2:
    ax.plot(p.x, p.y, "o", ms=3.6, mfc="white", mec="#1f4e8c", mew=.9, zorder=5)
for p, _ in pt1_tour + pt2_tour:
    ax.plot(p.x, p.y, "D", ms=5.5, mfc="#27ae60", mec="white", mew=.8, zorder=6)
for p, _ in pt1_lodge + pt2_lodge:
    ax.plot(p.x, p.y, "D", ms=5.5, mfc="#8e44ad", mec="white", mew=.8, zorder=6)
STN = [("S1", "모빌리티 허브", term, (-40, -40)),
       ("S2", "휴식 스테이션(청호해변)", Point(coast1.interpolate(coast1.project(P(38.1975, 128.602))).coords[0]), (70, 25)),
       ("S3", "포토 스테이션(엑스포타워)", expo, (-30, -55)),
       ("S4", "로컬 스테이션(갯배·중앙시장)", P(38.2042, 128.5935), (-95, 20))]
for k, label, p, (ox, oy) in STN:
    ax.plot(p.x, p.y, marker="s", ms=11, mfc="#f39c12", mec="#7a4a00", mew=1.2, zorder=7)
    ax.text(p.x, p.y, k, fontsize=6.5, weight="bold", ha="center", va="center", zorder=8)
    ax.annotate(label, (p.x, p.y), xytext=(ox, oy), textcoords="offset points", fontsize=7.5, weight="bold",
                ha="center", bbox=dict(boxstyle="round,pad=.25", fc="white", ec="#f39c12", lw=.8),
                arrowprops=dict(arrowstyle="-", color="#7a4a00", lw=.7), zorder=8)
LBL = [("청초호", 38.1985, 128.5870, 11, "#1f4e8c"), ("영랑호", 38.2175, 128.5790, 10, "#1f4e8c"), ("동해", 38.200, 128.6085, 11, "#1f4e8c"),
       ("속초해수욕장", 38.1880, 128.6045, 7.5, "#333"), ("아바이마을", 38.1990, 128.5962, 7.5, "#333"),
       ("청호동 해안 자전거길", 38.1925, 128.6050, 7, "#333"), ("중앙시장", 38.2062, 128.5872, 8, "#333"), ("동명항·영금정(2단계)", 38.2120, 128.6040, 7, "#555")]
for t, la, lo, fs, col in LBL:
    x, y = to_m(lo, la); ax.text(float(x), float(y), t, fontsize=fs, color=col, ha="center", weight="bold" if fs > 9 else "normal",
                                  rotation=-50 if "자전거길" in t else 0)
scalebar(ax, cx0 + 200, cy0 + 200, 500)
ax.legend(handles=[Line2D([], [], color="#2c6fb7", lw=3, label="1단계 가상주차 회랑"),
                   Line2D([], [], color="#2c6fb7", lw=2, ls=":", label="2단계 회랑"),
                   Line2D([], [], marker="o", ls="", mfc="#e74c3c", mec="white", ms=7, label="A등급 가상주차구역 (50~100m 간격)"),
                   Line2D([], [], marker="o", ls="", mfc="#1f4e8c", mec="white", ms=6, label="B등급 가상주차구역 (150~200m 간격)"),
                   Line2D([], [], marker="o", ls="", mfc="white", mec="#1f4e8c", ms=5, label="2단계 가상주차구역"),
                   Line2D([], [], marker="D", ls="", mfc="#27ae60", mec="white", ms=6, label="관광지형 가상주차구역"),
                   Line2D([], [], marker="D", ls="", mfc="#8e44ad", mec="white", ms=6, label="숙박시설형 가상주차구역"),
                   Line2D([], [], marker="s", ls="", mfc="#f39c12", mec="#7a4a00", ms=9, label="MaaS 스테이션"),
                   Patch(fc="#e74c3c", alpha=.2, ec="#e74c3c", ls="--", label="A등급 구역(입지점수 0.6 이상)"),
                   Patch(fc="#f5b041", alpha=.2, label="B등급 후보(입지점수 0.35~0.6)"),
                   Line2D([], [], marker="o", ls="", mfc="#7d3c98", mec="none", ms=3, label="숙박시설(영업)"),
                   Line2D([], [], marker="^", ls="", mfc="#1e8449", mec="none", ms=5, label="관광지(TourAPI)"),
                   Line2D([], [], marker="s", ls="", mfc="#555", mec="none", ms=3, label="버스정류장")],
          loc="upper left", fontsize=7, frameon=True, framealpha=.95).set_zorder(20)
ax.set_title("청초호·해안길 가상주차제 구상도 (개략)", fontsize=12, weight="bold")
fig.tight_layout(); fig.savefig(os.path.join(OUT, "map_concept.png")); plt.close(fig)
print(json.dumps({k: v for k, v in stats.items() if k != "dong"}, ensure_ascii=False, indent=1))
for r in stats["dong"]:
    print(r)
for nm, ln in phase1 + phase2:
    s = spots([(nm, ln)])
    print("SEG", nm, round(ln.length), len(s), sum(a for _, a in s))

from scipy.spatial import cKDTree
for i, g in enumerate(sorted(getattr(zoneU, "geoms", [zoneU]), key=lambda g: -g.area)):
    c = g.centroid; inL = sum(g.buffer(1).contains(Point(*q)) for q in Lp); inT = [j for j, q in enumerate(Tp) if g.buffer(1).contains(Point(*q))]
    inB = sum(g.buffer(1).contains(Point(*q)) for q in Bp)
    lo, la = to_ll(c.x, c.y)
    d1 = min(ln.distance(c) for _, ln in phase1); d2 = min(ln.distance(c) for _, ln in phase2)
    print("CL", i, round(g.area / 1e4, 1), "ha", round(float(la), 4), round(float(lo), 4), "L", inL, "T", len(inT), "B", inB, "d1", round(d1), "d2", round(d2))
