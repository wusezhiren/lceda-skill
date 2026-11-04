#!/usr/bin/env python3
"""摆件阶段的快速几何检查（比立创 DRC 快，摆一次查一次）。

用法：pcb_check.py dump.json [--gap 0.15] [--edge 0.3] [--body 0.1] [--silk]
  - 异网络焊盘间距 < gap（按旋转后的外接矩形近似，偏保守）
  - 焊盘离板框 < edge
  - 器件“焊盘包络 + body”互相压住（同面器件）——bbox 里含丝印，比较粗，故用焊盘包络
  - --silk：可见位号与焊盘/其他位号/板框重叠（位号须为居中对齐，pcb_silk.js 已统一）
dump.json 由 scripts/pcb_dump.js 导出。退出码：有问题为 1。
"""
import argparse, json, math, sys

ap = argparse.ArgumentParser()
ap.add_argument('dump'); ap.add_argument('--gap', type=float, default=0.15)
ap.add_argument('--edge', type=float, default=0.3); ap.add_argument('--body', type=float, default=0.1)
ap.add_argument('--silk', action='store_true')
a = ap.parse_args()
d = json.load(open(a.dump))
X0, Y0, X1, Y1 = d.get('board') or [0, 0, 1e9, 1e9]


def pad_box(x, y, w, h, rot):
    t = math.radians(rot or 0)
    hw = abs(math.cos(t)) * w / 2 + abs(math.sin(t)) * h / 2
    hh = abs(math.sin(t)) * w / 2 + abs(math.cos(t)) * h / 2
    return (x - hw, y - hh, x + hw, y + hh)


def gap(A, B):
    dx = max(B[0] - A[2], A[0] - B[2], 0); dy = max(B[1] - A[3], A[1] - B[3], 0)
    return math.hypot(dx, dy)


def pgap(A, B):
    """A/B = (box, circle)；圆形焊盘（ELLIPSE 且宽高相等）按真实圆算"""
    if A[1] and B[1]: return max(math.hypot(A[1][0] - B[1][0], A[1][1] - B[1][1]) - A[1][2] - B[1][2], 0)
    if B[1]: A, B = B, A
    if A[1]:
        x, y, r = A[1]; b = B[0]
        return max(math.hypot(max(b[0] - x, x - b[2], 0), max(b[1] - y, y - b[3], 0)) - r, 0)
    return gap(A[0], B[0])


def overlap(A, B): return A[0] < B[2] and B[0] < A[2] and A[1] < B[3] and B[1] < A[3]


pads, env = [], {}
for ref, c in d['comps'].items():
    boxes = []
    for num, net, x, y, sh, w, h, rot, lay in c['pads']:
        b = pad_box(x, y, w, h, rot); boxes.append(b)
        circ = (x, y, w / 2) if sh == 'ELLIPSE' and abs(w - h) < 1e-3 else None
        pads.append((f'{ref}.{num}', ref, net, b, 0 if lay == 12 else lay, circ))
    if boxes:
        env[ref] = (min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes), c['layer'])
for num, net, x, y, sh, w, h, lay in d.get('free', []):
    circ = (x, y, w / 2) if sh == 'ELLIPSE' and abs(w - h) < 1e-3 else None
    pads.append((f'PAD.{num}', f'PAD.{num}', net, (x - w / 2, y - h / 2, x + w / 2, y + h / 2), 0 if lay == 12 else lay, circ))

bad = 0
res = []
for i in range(len(pads)):
    for j in range(i + 1, len(pads)):
        A, B = pads[i], pads[j]
        if A[1] == B[1] or (A[4] and B[4] and A[4] != B[4]) or (A[2] and A[2] == B[2]): continue
        g = pgap((A[3], A[5]), (B[3], B[5]))
        if g < a.gap: res.append((g, f'焊盘间距 {g:.3f}mm  {A[0]}({A[2] or "NC"}) ↔ {B[0]}({B[2] or "NC"})'))
for g, s in sorted(res): print(s); bad += 1
for name, ref, net, b, lay, _ in pads:
    e = min(b[0] - X0, b[1] - Y0, X1 - b[2], Y1 - b[3])
    if e < a.edge and not name.startswith('J'): print(f'近板边 {e:.2f}mm  {name}'); bad += 1
refs = sorted(env)
for i in range(len(refs)):
    for j in range(i + 1, len(refs)):
        A, B = env[refs[i]], env[refs[j]]
        if A[4] != B[4]: continue
        Ae = (A[0] - a.body, A[1] - a.body, A[2] + a.body, A[3] + a.body)
        if overlap(Ae, B[:4]): print(f'器件焊盘包络互压  {refs[i]} ↔ {refs[j]}'); bad += 1
if a.silk:
    boxes = []
    for ref, c in d['comps'].items():
        s = c.get('des')
        if not s or not s['visible']: continue
        w = 0.62 * s['size'] * len(ref) + 0.1; h = s['size'] + 0.1
        if s['rot'] in (90, 270, -90): w, h = h, w
        boxes.append((ref, (s['x'] - w / 2, s['y'] - h / 2, s['x'] + w / 2, s['y'] + h / 2), s['layer']))
    for ref, b, lay in boxes:
        if b[0] < X0 or b[1] < Y0 or b[2] > X1 or b[3] > Y1: print(f'丝印出板  {ref}'); bad += 1
        side = 1 if lay in (3, 1) else 2
        for name, pref, net, pb, play, _ in pads:
            if play in (0, side) and overlap(b, pb): print(f'丝印压焊盘  {ref} ↔ {name}'); bad += 1; break
    for i in range(len(boxes)):
        for j in range(i + 1, len(boxes)):
            if boxes[i][2] == boxes[j][2] and overlap(boxes[i][1], boxes[j][1]): print(f'丝印互压  {boxes[i][0]} ↔ {boxes[j][0]}'); bad += 1
print(f'共 {bad} 项')
sys.exit(1 if bad else 0)
