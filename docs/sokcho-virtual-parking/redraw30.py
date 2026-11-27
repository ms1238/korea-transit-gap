"""블록 안 구역을 표(1㎢당 30개 상한)의 개수로 고르게 다시 배치하고 후보지 지도 2장을 다시 그린다."""
import sys, os
OUTDIR = sys.argv[1]
sys.argv = ["analyze.py", OUTDIR]
src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "analyze.py")).read()
exec(src.split("# ---------- 후보지 위치도")[0])

import numpy as np
TARGET = {"교동·청초호 서측": 11, "중앙시장·갯배": 7, "엑스포타워·청초호 남서측": 5, "조양동(청초호 남측)": 6,
          "속초해수욕장·고속버스터미널": 11, "청호해변(해안 자전거길)": 8, "시외버스터미널·속초항": 5, "동명항·영금정·등대전망대": 5}


# 동해대로 선형: 주소가 '동해대로 N'(번길 제외)인 숙박·관광 좌표를 도로명 번호 순으로 이음
_dh = [x for x in json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "donghae_pts.json"))) if "번길" not in x[3]]
_seen, _line = set(), []
for la, lo, num, _ in sorted(_dh, key=lambda x: x[2]):
    if num in _seen:
        continue
    _seen.add(num); _line.append(tuple(map(float, to_m(lo, la))))
DONGHAE = LineString(_line).simplify(15)
ROADS = shapely.union_all([DONGHAE] + [ln for _, ln in phase1 + phase2])


def place(g, n, fixed):
    """동해대로와 회랑(호숫가, 해안길) 위 후보점에서 n개를 고름: 블록 안 최대 거리를 줄이는 k-중심 선택 후 교환 개선.
    도로 위 후보만으로 커버가 안 되는 곳(직선 170m 초과)에만 블록 안쪽 점을 허용."""
    xs0, ys0, xs1, ys1 = g.bounds
    samp = np.array([(x, y) for x in np.arange(xs0, xs1, 15) for y in np.arange(ys0, ys1, 15) if g.contains(Point(x, y))])
    road = ROADS.intersection(g.buffer(20))
    cand = []
    for ln in getattr(road, "geoms", [road]):
        if ln.length == 0 or ln.geom_type not in ("LineString", "LinearRing"):
            continue
        cand += [ln.interpolate(t).coords[0] for t in np.arange(0, ln.length + 1, 25)]
    inner = [(x, y) for x in np.arange(xs0, xs1, 30) for y in np.arange(ys0, ys1, 30) if g.buffer(-12).contains(Point(x, y))]
    cand = np.array(cand if cand else inner, float); inner = np.array(inner, float)
    D = lambda P_: np.min([np.hypot(*(samp - p).T) for p in P_], axis=0)
    pts = [np.array(q.coords[0]) for q in fixed]
    if not pts:
        pts = [cand[np.argmin(np.hypot(*(cand - samp.mean(axis=0)).T))]]
    while len(pts) < n:
        d = D(pts)
        far = samp[np.argmax(d)]
        pool = cand if (np.min(np.hypot(*(cand - far).T)) < 170 or not len(inner)) else np.vstack([cand, inner])
        # 가장 먼 표본점을 가장 잘 줄이는 후보
        best = pool[np.argmin(np.hypot(*(pool - far).T))]
        pts.append(best)
    pts = [np.array(p, float) for p in pts]; nf = len(fixed)
    for _ in range(3):  # 교환 개선: 각 점을 후보 중 최대거리 최소가 되는 곳으로
        for k in range(nf, len(pts)):
            others = pts[:k] + pts[k + 1:]
            base_d = D(others)
            pool = cand
            best, bv = pts[k], np.percentile(np.minimum(base_d, np.hypot(*(samp - pts[k]).T)), 95)
            for q in pool[::2]:
                v = np.percentile(np.minimum(base_d, np.hypot(*(samp - q).T)), 95)
                if v < bv - 1:
                    best, bv = q, v
            pts[k] = best
    d = D(pts)
    onroad = sum(1 for p in pts[nf:] if ROADS.distance(Point(*p)) < 25)
    return [Point(*p) for p in pts], float(np.percentile(d, 95)), float(d.max()), onroad


for c in C1 + C2:
    n = TARGET[c["name"]]
    if c["name"].startswith("청호해변"):
        gb = c["geom"].buffer(30)
        c["block_pts"] = [p for p, _ in sp1 if gb.contains(p)][:n]
        c["p95"] = c["dmax"] = 0; c["onroad"] = n
    else:
        fixed = [STATIONS[k] for k in c["stations"]]
        c["block_pts"], c["p95"], c["dmax"], c["onroad"] = place(c["geom"], n, fixed)
    c["total"] = len(c["block_pts"])
    print("BLOCK", c["name"], c["total"], f"{c['total'] / c['area']:.1f}/km2 p95 {c['p95']:.0f}m max {c['dmax']:.0f}m onroad {c['onroad']}")

inb = shapely.union_all([c["geom"].buffer(30) for c in C1 + C2])
out1 = [p for p in allspots1 if not inb.contains(p)]
out2 = [p for p in allspots2 if not inb.contains(p)]
print("OUT", len(out1), len(out2), "P1", sum(c["total"] for c in C1), "P2", sum(c["total"] for c in C2))

NUM = "①②③④⑤⑥⑦⑧⑨"
BLK = "#16a085"


def draw_cand(ax, c, i, lw=2.4, ls="-", col="#d7191c", label=True, fs=11):
    g = c["geom"]
    ax.fill(*g.exterior.xy, color=col, alpha=.10, lw=0, zorder=3)
    ax.plot(*g.exterior.xy, color=col, lw=lw, ls=ls, zorder=6)
    if label:
        rp = g.representative_point()
        ax.text(rp.x, rp.y, NUM[i], fontsize=fs, weight="bold", color=col, ha="center", va="center", zorder=9,
                bbox=dict(boxstyle="circle,pad=.15", fc="white", ec=col, lw=1))


def stations_on(ax, ms=10, fs=6.5):
    for k, q in STATIONS.items():
        ax.plot(q.x, q.y, marker="s", ms=ms, mfc="#f39c12", mec="#7a4a00", mew=1.1, zorder=10, clip_on=True)
        ax.text(q.x, q.y, k, fontsize=fs, weight="bold", ha="center", va="center", zorder=11, clip_on=True)


def dots(ax, pts, col, ms):
    for p in pts:
        ax.plot(p.x, p.y, "o", ms=ms, mfc=col, mec="white", mew=.6, zorder=8, clip_on=True)


ALL = [(c, i, "-") for i, c in enumerate(C1)] + [(c, len(C1) + j, "--") for j, c in enumerate(C2)]
fig, ax = plt.subplots(figsize=(8, 9.2), dpi=220)
base(ax, (cx0, cx1), (cy0, cy1), bnd=False)
for _, ln in phase1:
    ax.plot(*ln.xy, color="#2c6fb7", lw=1.6, alpha=.55)
for _, ln in phase2:
    ax.plot(*ln.xy, color="#2c6fb7", lw=1.2, alpha=.45, ls=(0, (2, 1.5)))
ax.plot(*DONGHAE.xy, color="#6c3483", lw=3.2, alpha=.75, solid_capstyle="round", zorder=5)
_lp = DONGHAE.interpolate(0.62, normalized=True)
ax.text(_lp.x, _lp.y - 70, "동해대로", fontsize=8, color="#6c3483", weight="bold", ha="center", zorder=9,
        bbox=dict(boxstyle="round,pad=.15", fc="white", ec="none", alpha=.8))
dots(ax, out1, "#1f4e8c", 3.2)
for c, i, ls in ALL:
    draw_cand(ax, c, i, ls=ls, col="#d7191c" if ls == "-" else "#e67e22")
    dots(ax, c["block_pts"], BLK, 4.6)
stations_on(ax)
scalebar(ax, cx0 + 200, cy0 + 200, 500)
ax.legend(handles=[Patch(fc="#d7191c", alpha=.25, ec="#d7191c", lw=2, label="1단계 후보지 블록(반납 의무)"),
                   Patch(fc="#e67e22", alpha=.25, ec="#e67e22", lw=2, ls="--", label="2단계 후보지 블록"),
                   Line2D([], [], marker="o", ls="", mfc=BLK, mec="white", ms=6, label="블록 안 가상주차구역(1㎢당 30개 상한)"),
                   Line2D([], [], marker="o", ls="", mfc="#1f4e8c", mec="white", ms=5, label="블록 밖 권장 구역(회랑·거점)"),
                   Line2D([], [], marker="s", ls="", mfc="#f39c12", mec="#7a4a00", ms=8, label="MaaS 스테이션"),
                   Line2D([], [], color="#2c6fb7", lw=2, alpha=.6, label="회랑"),
                   Line2D([], [], color="#6c3483", lw=3, alpha=.75, label="동해대로(보도 넓음)")],
          loc="upper left", fontsize=7.5, framealpha=.95).set_zorder(20)
ax.set_title("가상주차구역 후보지 위치도 (청초호·해안길)", fontsize=12, weight="bold")
fig.tight_layout(); fig.savefig(os.path.join(OUTDIR, "map_candidates.png")); plt.close(fig)

n = len(ALL); rows = (n + 1) // 2
fig, axs = plt.subplots(rows, 2, figsize=(8.2, 3.3 * rows), dpi=200)
for (c, i, ls), ax in zip(ALL, axs.flat):
    g = c["geom"]; b = g.bounds; w = max(b[2] - b[0], (b[3] - b[1]) * 1.4) / 2 + 220; h = w / 1.4
    mx, my = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
    base(ax, (mx - w, mx + w), (my - h, my + h), bnd=False)
    for _, ln in phase1 + phase2:
        ax.plot(*ln.xy, color="#2c6fb7", lw=1.2, alpha=.45)
    ax.plot(*DONGHAE.xy, color="#6c3483", lw=3, alpha=.7, zorder=5)
    dots(ax, out1 + out2, "#1f4e8c", 3.8)
    draw_cand(ax, c, i, lw=2.6, ls=ls, col="#d7191c" if ls == "-" else "#e67e22", label=False)
    dots(ax, c["block_pts"], BLK, 5.2)
    stations_on(ax, 11, 7)
    scalebar(ax, mx - w + 60, my - h + 60, 200)
    stx = ", ".join(c["stations"]) if c["stations"] else "-"
    ax.set_title(f"{NUM[i]} {c['name']}" + (" (2단계)" if ls == "--" else ""), fontsize=9.5, weight="bold", loc="left")
    ax.set_xlabel(f"(면적) {c['area']:.2f}㎢ / (가상주차구역) {c['total']}개소 / (1㎢당) {c['total'] / c['area']:.0f}개 / (스테이션) {stx}", fontsize=7.8)
for ax in list(axs.flat)[n:]:
    ax.axis("off")
fig.tight_layout(); fig.savefig(os.path.join(OUTDIR, "map_candidates_panels.png")); plt.close(fig)
