#!/usr/bin/env python3
"""铺铜后分析 GND（或其他平面网络）连通：列出与主地断开、且含焊盘/过孔的孤岛。

用法：gnd_islands.py dump.json [--net GND] [--tol 0.02] [--out islands.json] [--png islands.png]
dump.json 由 pcb_dump.js 导出（需含 pours，即铺铜已重建）。退出码：有孤岛为 1。

为什么需要它：立创 DRC 的 "Connection Error … is disconnected from other objects of the same network"
报的是孤岛之间**缺失飞线的一个端点**，常落在主地一侧（如主地上的过孔），不等于"该对象所在块是孤岛"。
照着 DRC 报点逐个补线容易补错地方；先用本脚本找出真正的孤岛，再用 gnd_route.py 接回主地。
"""
import argparse, json, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pcbgeo import load, Board

ap = argparse.ArgumentParser()
ap.add_argument('dump'); ap.add_argument('--net', default='GND')
ap.add_argument('--tol', type=float, default=0.001, help='重叠面积阈值 mm²')
ap.add_argument('--out'); ap.add_argument('--png')
a = ap.parse_args()
d = load(a.dump)
if not d.get('pours'): sys.exit('dump 里没有 pours：先重建铺铜，并用新版 pcb_dump.js 导出')
B = Board(d)
gs = B.groups(a.net, a.tol)
names = lambda g: [B.objs[i][0] for i in g]
main = gs[0]
islands = []
for g in gs[1:]:
    items = [n for n in names(g) if not n.startswith(('pour', 'trk'))]
    if items: islands.append({'members': names(g), 'items': items,
                              'pour_area': round(sum(B.objs[i][3].area for i in g if B.objs[i][0].startswith('pour')), 2)})
print(f"{a.net}: 主地 {len(main)} 个对象，孤岛 {len(islands)} 个（含焊盘/过孔）")
for k, s in enumerate(islands): print(f"  [{k}] 铜 {s['pour_area']}mm²  {' '.join(s['items'][:8])}{' …' if len(s['items']) > 8 else ''}")
if a.out: json.dump({'net': a.net, 'main': names(main), 'islands': islands}, open(a.out, 'w'), ensure_ascii=False)
if a.png:
    import matplotlib; matplotlib.use('Agg'); import matplotlib.pyplot as plt
    mset = set(names(main)); X0, Y0, X1, Y1 = B.outline
    fig, axs = plt.subplots(1, 2, figsize=(14, 14 * (Y1 - Y0) / max(1, 2 * (X1 - X0))))
    def draw(ax, g, **kw):
        for p in getattr(g, 'geoms', [g]):
            if p.geom_type != 'Polygon': continue
            ax.fill(*p.exterior.xy, **kw)
            for h in p.interiors: ax.fill(*h.xy, fc='white', ec='none')
    for ax, L in zip(axs, (1, 2)):
        for n, net, ls, g in B.objs:
            if L not in ls: continue
            if n.startswith('pour'): draw(ax, g, fc='lightblue' if n in mset else 'orange', ec='b', lw=.3)
            elif net != a.net: draw(ax, g, fc='gray', alpha=.5)
            else: draw(ax, g, fc='green' if n in mset else 'red', alpha=.7)
        ax.set_xlim(X0, X1); ax.set_ylim(Y0, Y1); ax.set_aspect('equal'); ax.set_title(f'L{L}  blue=main  orange/red=island')
    plt.savefig(a.png, dpi=110, bbox_inches='tight')
sys.exit(1 if islands else 0)
