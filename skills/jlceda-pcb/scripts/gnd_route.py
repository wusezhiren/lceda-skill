#!/usr/bin/env python3
"""把 GND 孤岛接回主地：两层 8 邻域网格寻路，避开异网络铜，必要时打地过孔换层；可选铺缝合过孔。

用法：
  gnd_route.py dump.json out.json [--net GND] [--islands islands.json] [--width 0.3] [--gap 0.18]
               [--via 0.6,0.3] [--keepout x0,y0,x1,y1 ...] [--stitch 1.6] [--no-route]
  python3 lceda.py run scripts/apply_stitch.js --args-file out.json --timeout 600   # 下发 + 重铺 + DRC

流程：先 gnd_islands.py 确认孤岛 → 本脚本（建议先 --stitch 单跑一轮缝合孔，重铺后再导出、再寻路）→ apply → 重复到 DRC 0。
- 起点为整个孤岛（任一焊盘/铜块/过孔），终点为主地铺铜（内缩线宽一半）；输出 {vias:[[net,x,y]], lines:[[net,layer,pts,w]]}。
- 过孔不落在同网络贴片焊盘上，与已有孔中心距 ≥ 0.85mm，离板边 ≥ 0.6mm，避开 --keepout（天线净空等）。
- --stitch P：在上下层铺铜重叠处按间距 P 补缝合孔，每对"顶层铜块×底层铜块"至少一个，先把大块孤铜并进主地。
- 无路径时用 --width 0.2 --gap 0.16 再试；仍无路径说明被围死，需挪线（如把挡路的信号线改道腾位置）。
寻路结果是候选，下发后必须重铺铜 + DRC，并看图确认没有绕远的长地线。
"""
import argparse, heapq, json, math, os, sys
import numpy as np, shapely
from shapely.geometry import Point, LineString, box
from shapely.ops import unary_union
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pcbgeo import load, Board

ap = argparse.ArgumentParser()
ap.add_argument('dump'); ap.add_argument('out'); ap.add_argument('--net', default='GND')
ap.add_argument('--islands', help='gnd_islands.py --out 的结果；省略则现算')
ap.add_argument('--tol', type=float, default=0.001)
ap.add_argument('--width', type=float, default=0.3); ap.add_argument('--gap', type=float, default=0.18)
ap.add_argument('--via', default='0.6,0.3', help='外径,孔径 mm')
ap.add_argument('--keepout', nargs='*', default=[], help='禁布矩形 x0,y0,x1,y1（mm）')
ap.add_argument('--grid', type=float, default=0.05)
ap.add_argument('--via-cost', type=float, default=1.5, help='换层代价，折合 mm 走线')
ap.add_argument('--stitch', type=float, default=0, help='缝合孔间距 mm，0 不铺')
ap.add_argument('--no-route', action='store_true', help='只铺缝合孔，不寻路')
a = ap.parse_args()
d = load(a.dump); B = Board(d)
NET = a.net; TW = a.width; CL = a.gap; G = a.grid
VD, VH = (float(v) for v in a.via.split(',')); VR = VD / 2
X0, Y0, X1, Y1 = (round(v, 2) for v in B.outline)
keep = unary_union([box(*map(float, k.split(','))) for k in a.keepout]) if a.keepout else None
F = {L: B.copper(L, exclude_net=NET) for L in (1, 2)}
GS = {L: unary_union([g for n, nt, ls, g in B.objs if nt == NET and L in ls and not n.startswith(('pour', 'trk', 'via'))]) for L in (1, 2)}
gs = B.groups(NET, a.tol)
main_ids = set(gs[0])
main = {L: unary_union([B.objs[i][3] for i in gs[0] if B.objs[i][0].startswith('pour') and L in B.objs[i][2]]) for L in (1, 2)}
if a.islands: isl = [set(s['members']) for s in json.load(open(a.islands))['islands']]
else: isl = [set(B.objs[i][0] for i in g) for g in gs[1:] if any(not B.objs[i][0].startswith(('pour', 'trk')) for i in g)]
holes = list(B.holes)
res = {'vias': [], 'lines': [], 'failed': [], 'via': [VD, VH]}

xs = np.arange(X0, X1 + 1e-9, G); ys = np.arange(Y0, Y1 + 1e-9, G)
XX, YY = np.meshgrid(xs, ys, indexing='ij'); nx, ny = XX.shape
inside = lambda m: (XX > X0 + m) & (XX < X1 - m) & (YY > Y0 + m) & (YY < Y1 - m)
cx = lambda g: shapely.contains_xy(g, XX, YY) if g is not None and not g.is_empty else np.zeros(XX.shape, bool)
kz_t = cx(keep.buffer(TW / 2 + 0.1)) if keep else np.zeros(XX.shape, bool)
kz_v = cx(keep.buffer(VR + 0.15)) if keep else np.zeros(XX.shape, bool)
free = {L: ~cx(F[L].buffer(CL + TW / 2)) & inside(0.35) & ~kz_t for L in (1, 2)}
viaok = ~cx(F[1].buffer(CL + VR)) & ~cx(F[2].buffer(CL + VR)) & inside(0.6) & ~kz_v & ~cx(GS[1].buffer(0.05)) & ~cx(GS[2].buffer(0.05))
def block_hole(x, y):
    global viaok
    viaok &= ((XX - x) ** 2 + (YY - y) ** 2) >= 0.85 ** 2
for h in holes: block_hole(*h)

# 1) 缝合孔：上下层铺铜（任意块）重叠处
if a.stitch > 0:
    pours = {L: [(n, g) for n, nt, ls, g in B.objs if n.startswith('pour') and nt == NET and L in ls] for L in (1, 2)}
    both = unary_union([g for _, g in pours[1]]).buffer(-(VR + 0.05)).intersection(unary_union([g for _, g in pours[2]]).buffer(-(VR + 0.05)))
    ok = viaok & cx(both)
    pid = lambda L, x, y: next((n for n, g in pours[L] if g.contains(Point(x, y))), None)
    pts = [(float(xs[i]), float(ys[j])) for i, j in zip(*np.nonzero(ok)) if i % 5 == 0 and j % 5 == 0]
    seen = set(); chosen = []
    far = lambda x, y, dd: all(math.hypot(x - p, y - q) >= dd for p, q in holes)
    for x, y in pts:                      # 每对铜块先给一个
        k = (pid(1, x, y), pid(2, x, y))
        if k not in seen and far(x, y, 1.0): seen.add(k); chosen.append((x, y)); holes.append((x, y)); block_hole(x, y)
    for x, y in pts:
        if far(x, y, a.stitch): chosen.append((x, y)); holes.append((x, y)); block_hole(x, y)
    res['vias'] += [[NET, round(x, 3), round(y, 3)] for x, y in chosen]
    print(f'缝合孔 {len(chosen)} 个（铜块组合 {len(seen)}）')

# 2) 孤岛寻路
D8 = [(1, 0, 1), (-1, 0, 1), (0, 1, 1), (0, -1, 1), (1, 1, 1.414), (1, -1, 1.414), (-1, 1, 1.414), (-1, -1, 1.414)]
tgt = {L: cx(main[L].buffer(-(TW / 2 + 0.08))) for L in (1, 2)}
for k, members in enumerate([] if a.no_route else isl):
    msk = {L: cx(unary_union([g for n, nt, ls, g in B.objs if n in members and L in ls] or [Point(-99, -99)])) for L in (1, 2)}
    dist, prev, pq = {}, {}, []
    for L in (1, 2):
        for i, j in zip(*np.nonzero(msk[L])):
            dist[(L, i, j)] = 0; prev[(L, i, j)] = None; heapq.heappush(pq, (0, (L, i, j)))
    found = None
    while pq:
        dc, key = heapq.heappop(pq)
        if dist.get(key, 1e18) < dc: continue
        L, i, j = key
        if tgt[L][i, j]: found = key; break
        if dc > 15 / G: break
        for di, dj, c in D8:
            ii, jj = i + di, j + dj
            if 0 <= ii < nx and 0 <= jj < ny and (free[L][ii, jj] or msk[L][ii, jj]):
                kk = (L, ii, jj); nd = dc + c
                if nd < dist.get(kk, 1e18): dist[kk] = nd; prev[kk] = key; heapq.heappush(pq, (nd, kk))
        if viaok[i, j] and free[1][i, j] and free[2][i, j]:
            kk = (3 - L, i, j); nd = dc + a.via_cost / G
            if nd < dist.get(kk, 1e18): dist[kk] = nd; prev[kk] = key; heapq.heappush(pq, (nd, kk))
    label = sorted(n for n in members if not n.startswith(('pour', 'trk')))[:3]
    if not found: res['failed'].append(label); print(f'  [{k}] 无路径 {label}'); continue
    path = []; key = found
    while key: path.append(key); key = prev[key]
    path.reverse()
    segs, cur, vias = [], [path[0]], []
    for p in path[1:]:
        if p[0] != cur[-1][0]: vias.append((float(xs[p[1]]), float(ys[p[2]]))); segs.append(cur); cur = [p]
        else: cur.append(p)
    segs.append(cur)
    for sg in segs:
        if len(sg) < 2: continue
        L = sg[0][0]; pts = [(float(xs[i]), float(ys[j])) for _, i, j in sg]
        for tol in (0.2, 0.12, 0.07, 0.03):     # 抹掉网格锯齿，仍须满足间距
            cand = list(LineString(pts).simplify(tol).coords); body = LineString(cand).buffer(TW / 2)
            if body.distance(F[L]) >= CL - 0.005 and not (keep and body.intersects(keep)): pts = cand; break
        res['lines'].append([NET, L, [[round(x, 3), round(y, 3)] for x, y in pts], TW])
    for x, y in vias: res['vias'].append([NET, round(x, 3), round(y, 3)]); block_hole(x, y)
    print(f'  [{k}] {label} 长 {dist[found] * G:.2f}mm 过孔 {len(vias)}')
json.dump(res, open(a.out, 'w'), ensure_ascii=False)
print(f"输出 {a.out}: 过孔 {len(res['vias'])} 走线 {len(res['lines'])} 失败 {len(res['failed'])}")
sys.exit(1 if res['failed'] else 0)
