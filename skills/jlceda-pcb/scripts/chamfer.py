#!/usr/bin/env python3
"""走线拐角倒角：把 ≤134° 的二度拐点（非焊盘/过孔内）切成 45° 斜段，逐个校验与异网络铜的间距。

用法：chamfer.py dump.json out.json [--gap 0.17] [--cut 0.5] [--nets GND,+5V]
  python3 lceda.py run scripts/apply_stitch.js --args-file out.json --timeout 600
一条线段两端都有拐角时一轮只处理一端：重新导出后再跑，直到报 0。T 形分支（度 ≥3）不动。
输出 {del:[[net,layer,[x1,y1],[x2,y2]]], lines:[[net,layer,pts,w]]}，由 apply_stitch.js 先删后建。
"""
import argparse, json, math, os, sys
from collections import defaultdict
from shapely.geometry import Point, LineString
from shapely.ops import unary_union
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pcbgeo import load, Board, layers_of, pad_geom

ap = argparse.ArgumentParser()
ap.add_argument('dump'); ap.add_argument('out')
ap.add_argument('--gap', type=float, default=0.17); ap.add_argument('--cut', type=float, default=0.5, help='最大切角长度 mm')
ap.add_argument('--nets', help='只处理这些网络（逗号分隔）')
a = ap.parse_args()
d = load(a.dump); B = Board(d)
only = set(a.nets.split(',')) if a.nets else None
r3 = lambda p: (round(p[0], 3), round(p[1], 3))
segs = [(l[0], l[1], r3((l[2], l[3])), r3((l[4], l[5])), l[6]) for l in d['lines'] if l[0] in (1, 2) and (l[2], l[3]) != (l[4], l[5])]
ends = defaultdict(list)
for s in segs: ends[(s[0], s[1], s[2])].append(s); ends[(s[0], s[1], s[3])].append(s)
padv = {L: unary_union([g for n, nt, ls, g in B.objs if L in ls and not n.startswith(('pour', 'trk'))]) for L in (1, 2)}
fc = {}
res = {'del': [], 'lines': []}; used = set()
for (L, net, p), ss in ends.items():
    if len(ss) != 2 or (only and net not in only): continue
    sa, sb = ss
    if id(sa) in used or id(sb) in used or padv[L].contains(Point(p)): continue
    qa = sa[3] if sa[2] == p else sa[2]; qb = sb[3] if sb[2] == p else sb[2]
    va = (qa[0] - p[0], qa[1] - p[1]); vb = (qb[0] - p[0], qb[1] - p[1]); la, lb = math.hypot(*va), math.hypot(*vb)
    ang = math.degrees(math.acos(max(-1, min(1, (va[0] * vb[0] + va[1] * vb[1]) / la / lb))))
    if ang >= 134: continue
    w = max(sa[4], sb[4])
    if (L, net) not in fc: fc[(L, net)] = B.copper(L, exclude_net=net)
    for c in [x for x in (a.cut, 0.4, 0.3, 0.2, 0.12) if x <= a.cut]:
        c1 = c2 = min(c, la * 0.45, lb * 0.45)
        pa = (p[0] + va[0] / la * c1, p[1] + va[1] / la * c1); pb = (p[0] + vb[0] / lb * c2, p[1] + vb[1] / lb * c2)
        if LineString([pa, pb]).buffer(w / 2).distance(fc[(L, net)]) >= a.gap:
            for s, q, pn in ((sa, qa, pa), (sb, qb, pb)):
                res['del'].append([net, L, list(s[2]), list(s[3])]); res['lines'].append([net, L, [list(r3(pn)), list(q)], s[4]])
            res['lines'].append([net, L, [list(r3(pa)), list(r3(pb))], w])
            used.add(id(sa)); used.add(id(sb)); break
json.dump(res, open(a.out, 'w'), ensure_ascii=False)
print(f"倒角 {len(res['del']) // 2} 处 → {a.out}")
