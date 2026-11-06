"""pcb_dump.js 导出数据的几何模型（shapely，单位 mm）：焊盘/走线/过孔/铺铜填充、异网络铜、同网络连通分组。

被 gnd_islands.py / gnd_route.py / chamfer.py 共用。需要 shapely≥2、numpy（pip install shapely）。
铺铜填充来自 pcb_PrimitivePoured.getState_PourFills()：坐标单位 10mil；complexPolygon 为多环列表，
按奇偶规则合成（逐环对称差，首环不一定是外环）；fill=false 的条目是热焊辐条等描边折线（lineWidth 同单位），须按线宽膨胀；'ARC' 后跟 [扫角°, 终点x, 终点y]，须按真实圆弧展开——
用弦近似会在细铜颈处多算铜，把 DRC 认为断开的区域误判为连通。
"""
import json, math
from shapely.geometry import Point, LineString, Polygon, box
from shapely.ops import unary_union
from shapely.validation import make_valid
from shapely import affinity

POUR_UNIT = 0.254          # 10mil → mm
TOP, BOT, MULTI = 1, 2, 12


def load(path):
    d = json.load(open(path))
    return d.get('result', d) if isinstance(d, dict) else d


def layers_of(l):
    return {TOP, BOT} if l == MULTI else {l}


def pad_geom(x, y, shape, w, h, rot, poly=None):
    if poly and len(poly) > 2: return make_valid(Polygon(poly))
    if shape in ('ELLIPSE', 'OVAL') and abs(w - h) < 1e-3: return Point(x, y).buffer(w / 2)
    if not w or not h: return Point(x, y).buffer(0.1)
    if shape == 'ELLIPSE':
        g = affinity.scale(Point(x, y).buffer(1), w / 2, h / 2, origin=(x, y))
    elif shape == 'OVAL':          # 跑道形：短边为直径的两端半圆
        r = min(w, h) / 2; dx, dy = (w / 2 - r, 0) if w >= h else (0, h / 2 - r)
        g = LineString([(x - dx, y - dy), (x + dx, y + dy)]).buffer(r) if dx or dy else Point(x, y).buffer(r)
    else:
        g = box(x - w / 2, y - h / 2, x + w / 2, y + h / 2)
    return affinity.rotate(g, rot or 0, origin=(x, y))


def _ring(tok):
    pts = [(tok[0], tok[1])]; i = 2; mode = 'L'
    while i < len(tok):
        t = tok[i]
        if isinstance(t, str): mode = t; i += 1; continue
        if mode == 'ARC':
            ang, ex, ey = tok[i], tok[i + 1], tok[i + 2]; i += 3
            sx, sy = pts[-1]; th = math.radians(ang)
            c = math.hypot(ex - sx, ey - sy)
            if abs(th) > 1e-6 and c > 1e-9:
                h = c / 2 / math.tan(th / 2)
                cx = (sx + ex) / 2 - (ey - sy) / c * h; cy = (sy + ey) / 2 + (ex - sx) / c * h
                a0 = math.atan2(sy - cy, sx - cx); R = math.hypot(sx - cx, sy - cy)
                n = max(2, int(abs(th) / math.radians(10)))
                pts += [(cx + R * math.cos(a0 + th * k / n), cy + R * math.sin(a0 + th * k / n)) for k in range(1, n)]
            pts.append((ex, ey)); continue
        pts.append((tok[i], tok[i + 1])); i += 2
    return [(x * POUR_UNIT, y * POUR_UNIT) for x, y in pts]


def pour_geom(complex_polygon, filled=True, line_width=0):
    rings = complex_polygon if complex_polygon and isinstance(complex_polygon[0], list) else [complex_polygon]
    if not filled:   # 热焊辐条等：描边折线，线宽单位同为 10mil
        w = (line_width or 1) * POUR_UNIT
        return unary_union([LineString(r).buffer(w / 2) for r in map(_ring, rings) if len(r) > 1])
    g = None
    for r in rings:
        pts = _ring(r)
        if len(pts) < 3: continue
        p = make_valid(Polygon(pts))
        g = p if g is None else g.symmetric_difference(p)
    return g


class Board:
    """objs: [(名称, 网络, 层集合, 几何)]；名称形如 'R9.2@14.50,11.43' / 'via@x,y' / 'trk#i' / 'pour1#k'。"""

    def __init__(self, dump):
        self.d = dump
        self.outline = dump.get('board') or [0, 0, 100, 100]
        self.objs = []; self.holes = []
        for ref, c in dump['comps'].items():
            for p in c['pads']:
                g = pad_geom(p[2], p[3], p[4], p[5], p[6], p[7], p[9] if len(p) > 9 else None)
                self.objs.append((f"{ref}.{p[0]}@{p[2]:.2f},{p[3]:.2f}", p[1], layers_of(p[8]), g))
                if p[8] == MULTI: self.holes.append((p[2], p[3]))
        for p in dump.get('free', []):
            self.objs.append((f"PAD.{p[0]}@{p[2]:.2f},{p[3]:.2f}", p[1], layers_of(p[7]), pad_geom(p[2], p[3], p[4], p[5], p[6], 0)))
            if p[7] == MULTI: self.holes.append((p[2], p[3]))
        for i, l in enumerate(dump.get('lines', [])):
            if l[0] in (TOP, BOT) and (l[2], l[3]) != (l[4], l[5]):
                self.objs.append((f"trk#{i}", l[1], {l[0]}, LineString([(l[2], l[3]), (l[4], l[5])]).buffer(l[6] / 2)))
        for v in dump.get('vias', []):
            self.objs.append((f"via@{v[1]:.2f},{v[2]:.2f}", v[0], {TOP, BOT}, Point(v[1], v[2]).buffer(v[3] / 2)))
            self.holes.append((v[1], v[2]))
        for o in dump.get('pours', []):
            for k, f in enumerate(o['fills']):
                g = pour_geom(f['path']['complexPolygon'], f.get('fill', True), f.get('lineWidth', 0))
                if g is not None and not g.is_empty:
                    self.objs.append((f"pour{o['layer']}#{k}", o['net'], {o['layer']}, g))

    def copper(self, layer, net=None, exclude_net=None):
        return unary_union([g for n, nt, ls, g in self.objs if layer in ls
                            and (net is None or nt == net) and (exclude_net is None or nt != exclude_net)])

    def groups(self, net='GND', tol=0.001):
        """同网络连通分组；两对象重叠面积 > tol(mm²) 才算相连（实测 0.001 与立创 DRC 一致：辐条与铺铜只有端部小块重叠）。按铺铜面积降序。"""
        idx = [i for i, o in enumerate(self.objs) if o[1] == net]
        par = {i: i for i in idx}
        def f(a):
            while par[a] != a: par[a] = par[par[a]]; a = par[a]
            return a
        for a in range(len(idx)):
            i = idx[a]
            for j in idx[a + 1:]:
                if self.objs[i][2] & self.objs[j][2] and self.objs[i][3].intersects(self.objs[j][3]) \
                        and self.objs[i][3].intersection(self.objs[j][3]).area > tol:
                    par[f(i)] = f(j)
        gs = {}
        for i in idx: gs.setdefault(f(i), []).append(i)
        area = lambda g: sum(self.objs[i][3].area for i in g if self.objs[i][0].startswith('pour'))
        return sorted(gs.values(), key=lambda g: (-area(g), -len(g)))
