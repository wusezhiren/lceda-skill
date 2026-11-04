#!/usr/bin/env python3
"""布线后给孤立的 GND（或其他平面网络）表层焊盘补地孔 + 短线。

用法：
  python3 gnd_stitch.py dump.json out.json R10.2 C3.2 [--net GND] [--via 0.45,0.2] [--gap 0.16] [--width 0.2]

dump.json 是 pcb_dump.js 的输出（布线导回之后、铺铜之前或之后都行，铺铜不算障碍）。
在焊盘周围 0.4~1.6mm 内找过孔位置：过孔与所有层的异网络铜（焊盘/走线/过孔）间距 ≥ gap，
焊盘→过孔的表层短线与异网络表层铜间距 ≥ gap。输出 {vias:[[net,x,y]], lines:[[net,layer,[[x,y],[x,y]],w]]}，
用 apply 脚本或 eda.pcb_PrimitiveVia.create / pcb_PrimitiveLine.create 下发。
"""
import argparse, json, math, sys

ap = argparse.ArgumentParser()
ap.add_argument('dump'); ap.add_argument('out'); ap.add_argument('pads', nargs='+', help='位号.焊盘号，如 R10.2')
ap.add_argument('--net', default='GND')
ap.add_argument('--via', default='0.45,0.2', help='过孔外径,孔径 mm')
ap.add_argument('--gap', type=float, default=0.16, help='与异网络铜的最小间距 mm（立创默认 0.152）')
ap.add_argument('--width', type=float, default=0.2, help='短线线宽 mm')
ap.add_argument('--edge', type=float, default=0.4, help='离板边最小距离 mm')
a = ap.parse_args()
d = json.load(open(a.dump))
VD, VH = (float(v) for v in a.via.split(','))
TOP, BOT, MULTI = 1, 2, 12

# 障碍：(net, layers, kind, geom)  kind: 'rect'(x1,y1,x2,y2) / 'seg'(x1,y1,x2,y2,w) / 'circ'(x,y,r)
obs = []
for ref, c in d['comps'].items():
    for num, net, x, y, sh, w, h, rot, lay in c['pads']:
        r = math.radians(rot or 0)
        hw = abs(math.cos(r)) * w / 2 + abs(math.sin(r)) * h / 2; hh = abs(math.sin(r)) * w / 2 + abs(math.cos(r)) * h / 2
        obs.append((net, 'all' if lay == MULTI else lay, 'rect', (x - hw, y - hh, x + hw, y + hh)))
for lay, net, x1, y1, x2, y2, w in d['lines']:
    obs.append((net, lay, 'seg', (x1, y1, x2, y2, w)))
for net, x, y, dia in d['vias']:
    obs.append((net, 'all', 'circ', (x, y, dia / 2)))

def d_pt_rect(px, py, b): return math.hypot(max(b[0] - px, px - b[2], 0), max(b[1] - py, py - b[3], 0))
def d_pt_seg(px, py, x1, y1, x2, y2):
    L2 = (x2 - x1) ** 2 + (y2 - y1) ** 2
    t = 0 if L2 == 0 else max(0, min(1, ((px - x1) * (x2 - x1) + (py - y1) * (y2 - y1)) / L2))
    return math.hypot(px - x1 - t * (x2 - x1), py - y1 - t * (y2 - y1))
def clear(px, py, r, layers):
    """点 (px,py) 半径 r 的圆，对给定层集合的异网络障碍是否满足间距"""
    for net, lay, kind, g in obs:
        if net == a.net or (lay != 'all' and lay not in layers): continue
        if kind == 'rect': dd = d_pt_rect(px, py, g)
        elif kind == 'seg': dd = d_pt_seg(px, py, *g[:4]) - g[4] / 2
        else: dd = math.hypot(px - g[0], py - g[1]) - g[2]
        if dd < r + a.gap: return False
    return True

bb = d.get('board') or [0, 0, 0, 0]          # pcb_dump.js：板框外包 [x0, y0, x1, y1]（含板框线宽）
X0, Y0, X1, Y1 = (round(v, 1) for v in bb)

res = {'vias': [], 'lines': [], 'failed': []}
for spec in a.pads:
    ref, num = spec.rsplit('.', 1)
    pad = next((p for p in d['comps'][ref]['pads'] if p[0] == num), None)
    if not pad: res['failed'].append(spec); continue
    _, net, x, y, *_ = pad
    best = None
    for rr in [0.4 + 0.1 * i for i in range(13)]:
        for k in range(24):
            ang = 2 * math.pi * k / 24; vx, vy = x + rr * math.cos(ang), y + rr * math.sin(ang)
            m = a.edge + VD / 2
            if X1 > X0 and not (X0 + m < vx < X1 - m and Y0 + m < vy < Y1 - m): continue
            if not clear(vx, vy, VD / 2, {TOP, BOT, 15, 16}): continue
            n = max(2, int(rr / 0.04))
            if all(clear(x + (vx - x) * i / n, y + (vy - y) * i / n, a.width / 2, {TOP}) for i in range(n + 1)):
                best = (round(vx, 3), round(vy, 3)); break
        if best: break
    if not best: res['failed'].append(spec); continue
    res['vias'].append([a.net, *best]); res['lines'].append([a.net, TOP, [[x, y], list(best)], a.width])
    obs.append((a.net, 'all', 'circ', (best[0], best[1], VD / 2)))   # 后续焊盘也要避开本次新加的（同网络不冲突，留作记录）
json.dump(res, open(a.out, 'w'), ensure_ascii=False)
print(json.dumps(res, ensure_ascii=False))
