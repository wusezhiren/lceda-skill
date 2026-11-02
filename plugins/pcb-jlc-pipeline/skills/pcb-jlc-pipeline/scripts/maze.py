"""
兜底迷宫布线（A*，双层 + 过孔）：给 Freerouting 漏掉的连接补线。

障碍物用 numpy 栅格化（焊盘按外接矩形、走线按胶囊、过孔按圆，再按线宽+间距膨胀），
网格默认 0.1mm。只用于少量残余连接，不追求最优。
"""

import heapq
import math

import numpy as np
import pcbnew

GRID = 0.1
CLEAR = 0.28          # 比规则 0.2 大，吸收 0.1mm 网格斜走时的切角误差
EDGE = 0.4


def _mm(v):
    return pcbnew.ToMM(v)


class Grid:
    def __init__(self, board):
        bb = board.GetBoardEdgesBoundingBox()
        self.x0, self.y0 = _mm(bb.GetLeft()), _mm(bb.GetTop())
        self.nx = int(round(_mm(bb.GetWidth()) / GRID)) + 1
        self.ny = int(round(_mm(bb.GetHeight()) / GRID)) + 1
        xs = self.x0 + np.arange(self.nx) * GRID
        ys = self.y0 + np.arange(self.ny) * GRID
        self.X, self.Y = np.meshgrid(xs, ys)          # [ny, nx]

    def ij(self, x, y):
        return (int(round((y - self.y0) / GRID)), int(round((x - self.x0) / GRID)))

    def xy(self, i, j):
        return (self.x0 + j * GRID, self.y0 + i * GRID)

    def window(self, x0, y0, x1, y1):
        i0 = max(0, int((y0 - self.y0) / GRID) - 1)
        i1 = min(self.ny, int((y1 - self.y0) / GRID) + 2)
        j0 = max(0, int((x0 - self.x0) / GRID) - 1)
        j1 = min(self.nx, int((x1 - self.x0) / GRID) + 2)
        return i0, i1, j0, j1


def _mark_rect(g, m, x0, y0, x1, y1):
    i0, i1, j0, j1 = g.window(x0, y0, x1, y1)
    X, Y = g.X[i0:i1, j0:j1], g.Y[i0:i1, j0:j1]
    m[i0:i1, j0:j1] |= (X >= x0) & (X <= x1) & (Y >= y0) & (Y <= y1)


def _mark_capsule(g, m, x1, y1, x2, y2, r):
    i0, i1, j0, j1 = g.window(min(x1, x2) - r, min(y1, y2) - r, max(x1, x2) + r, max(y1, y2) + r)
    X, Y = g.X[i0:i1, j0:j1], g.Y[i0:i1, j0:j1]
    dx, dy = x2 - x1, y2 - y1
    L2 = dx * dx + dy * dy
    if L2 == 0:
        d2 = (X - x1) ** 2 + (Y - y1) ** 2
    else:
        t = np.clip(((X - x1) * dx + (Y - y1) * dy) / L2, 0, 1)
        d2 = (X - (x1 + t * dx)) ** 2 + (Y - (y1 + t * dy)) ** 2
    m[i0:i1, j0:j1] |= d2 <= r * r


def obstacle_maps(board, g, net_code, inflate):
    """返回 {F_Cu: bool[ny,nx], B_Cu: ...}：True 表示该层此格不能放半宽为 inflate-CLEAR 的铜。"""
    maps = {pcbnew.F_Cu: np.zeros((g.ny, g.nx), bool), pcbnew.B_Cu: np.zeros((g.ny, g.nx), bool)}
    # 板边
    e = int(math.ceil((EDGE + inflate - CLEAR) / GRID))
    for m in maps.values():
        m[:e, :] = m[-e:, :] = True
        m[:, :e] = m[:, -e:] = True
    for fp in board.GetFootprints():
        for pad in fp.Pads():
            if pad.GetNetCode() == net_code and net_code > 0:
                continue
            bb = pad.GetBoundingBox()
            x0, y0, x1, y1 = _mm(bb.GetLeft()), _mm(bb.GetTop()), _mm(bb.GetRight()), _mm(bb.GetBottom())
            for layer, m in maps.items():
                if pad.IsOnLayer(layer):
                    _mark_rect(g, m, x0 - inflate, y0 - inflate, x1 + inflate, y1 + inflate)
            if pad.GetDrillSize().x > 0:     # 钻孔两层都挡
                for m in maps.values():
                    _mark_rect(g, m, x0 - inflate, y0 - inflate, x1 + inflate, y1 + inflate)
        for z in fp.Zones():
            if z.GetIsRuleArea():
                bb = z.Outline().BBox()
                for m in maps.values():
                    _mark_rect(g, m, _mm(bb.GetLeft()), _mm(bb.GetTop()), _mm(bb.GetRight()), _mm(bb.GetBottom()))
    for z in board.Zones():
        if z.GetIsRuleArea() and z.GetDoNotAllowTracks():
            bb = z.Outline().BBox()
            for layer, m in maps.items():
                if z.IsOnLayer(layer):
                    _mark_rect(g, m, _mm(bb.GetLeft()) - inflate + CLEAR, _mm(bb.GetTop()) - inflate + CLEAR,
                               _mm(bb.GetRight()) + inflate - CLEAR, _mm(bb.GetBottom()) + inflate - CLEAR)
    for t in board.GetTracks():
        if t.GetNetCode() == net_code and net_code > 0:
            continue
        if t.GetClass() == "PCB_VIA":
            x, y = _mm(t.GetPosition().x), _mm(t.GetPosition().y)
            r = _mm(t.GetWidth(pcbnew.F_Cu)) / 2 + inflate
            for m in maps.values():
                _mark_capsule(g, m, x, y, x, y, r)
        else:
            r = _mm(t.GetWidth()) / 2 + inflate
            m = maps.get(t.GetLayer())
            if m is not None:
                _mark_capsule(g, m, _mm(t.GetStart().x), _mm(t.GetStart().y),
                              _mm(t.GetEnd().x), _mm(t.GetEnd().y), r)
    return maps


def item_cells(g, item, layers_ok):
    """某个铜皮对象覆盖的格子 → [(layer, i, j)]"""
    cells = []
    if isinstance(item, pcbnew.PAD):
        bb = item.GetBoundingBox()
        x0, y0, x1, y1 = _mm(bb.GetLeft()), _mm(bb.GetTop()), _mm(bb.GetRight()), _mm(bb.GetBottom())
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        sx, sy = (x1 - x0) / 2 * 0.6, (y1 - y0) / 2 * 0.6
        layers = [l for l in layers_ok if item.IsOnLayer(l)]
        i0, i1, j0, j1 = g.window(cx - sx, cy - sy, cx + sx, cy + sy)
        for i in range(i0, i1):
            for j in range(j0, j1):
                x, y = g.xy(i, j)
                if abs(x - cx) <= sx and abs(y - cy) <= sy:
                    cells += [(l, i, j) for l in layers]
    elif item.GetClass() == "PCB_VIA":
        i, j = g.ij(_mm(item.GetPosition().x), _mm(item.GetPosition().y))
        cells += [(l, i, j) for l in layers_ok]
    else:
        x1, y1 = _mm(item.GetStart().x), _mm(item.GetStart().y)
        x2, y2 = _mm(item.GetEnd().x), _mm(item.GetEnd().y)
        n = max(1, int(math.hypot(x2 - x1, y2 - y1) / GRID))
        for k in range(n + 1):
            i, j = g.ij(x1 + (x2 - x1) * k / n, y1 + (y2 - y1) * k / n)
            cells.append((item.GetLayer(), i, j))
    return cells


def astar(g, free, via_free, starts, goals, via_cost=25):
    """free/via_free: {layer: bool[ny,nx]}（True=可走）。返回 [(layer,i,j)...] 或 None。"""
    layers = list(free.keys())
    goalset = set(goals)
    gi = np.mean([c[1] for c in goals])
    gj = np.mean([c[2] for c in goals])

    def h(i, j):
        return math.hypot(i - gi, j - gj)

    openq, came, cost = [], {}, {}
    for s in starts:
        cost[s] = 0
        heapq.heappush(openq, (h(s[1], s[2]), s))
    steps = [(-1, 0, 1), (1, 0, 1), (0, -1, 1), (0, 1, 1),
             (-1, -1, 1.414), (-1, 1, 1.414), (1, -1, 1.414), (1, 1, 1.414)]
    seen = 0
    while openq:
        _, cur = heapq.heappop(openq)
        if cur in goalset:
            path = [cur]
            while cur in came:
                cur = came[cur]
                path.append(cur)
            return path[::-1]
        seen += 1
        if seen > 600000:
            return None
        l, i, j = cur
        c0 = cost[cur]
        nbrs = []
        for di, dj, w in steps:
            ni, nj = i + di, j + dj
            if 0 <= ni < g.ny and 0 <= nj < g.nx and (free[l][ni, nj] or (l, ni, nj) in goalset):
                nbrs.append(((l, ni, nj), w))
        if via_free[i, j]:
            for l2 in layers:
                if l2 != l and (free[l2][i, j] or (l2, i, j) in goalset):
                    nbrs.append(((l2, i, j), via_cost))
        for nxt, w in nbrs:
            nc = c0 + w
            if nc < cost.get(nxt, 1e18):
                cost[nxt] = nc
                came[nxt] = cur
                heapq.heappush(openq, (nc + h(nxt[1], nxt[2]), nxt))
    return None


def route_connection(board, item_a, item_b, width=0.25, via_d=0.6, via_drill=0.3):
    """在 item_a 与 item_b（同网络）之间补一条线。先用宽松间距，找不到再收紧。成功返回 True。"""
    global CLEAR
    saved = CLEAR
    try:
        for c in (saved, 0.22):
            CLEAR = c
            if _route_connection(board, item_a, item_b, width, via_d, via_drill):
                return True
        return False
    finally:
        CLEAR = saved


def _route_connection(board, item_a, item_b, width, via_d, via_drill):
    net = item_a.GetNet()
    g = Grid(board)
    hw = width / 2
    obs = obstacle_maps(board, g, net.GetNetCode(), hw + CLEAR)
    vobs = obstacle_maps(board, g, net.GetNetCode(), via_d / 2 + CLEAR)
    for z in board.Zones():                       # 禁过孔区
        if z.GetIsRuleArea() and z.GetDoNotAllowVias():
            bb = z.Outline().BBox()
            _mark_rect(g, vobs[pcbnew.F_Cu], _mm(bb.GetLeft()), _mm(bb.GetTop()),
                       _mm(bb.GetRight()), _mm(bb.GetBottom()))
    free = {l: ~m for l, m in obs.items()}
    via_free = ~(vobs[pcbnew.F_Cu] | vobs[pcbnew.B_Cu])
    layers = [pcbnew.F_Cu, pcbnew.B_Cu]
    starts = item_cells(g, item_a, layers)
    goals = item_cells(g, item_b, layers)
    if not starts or not goals:
        return False
    for l, i, j in starts:          # 起点格强制可走（在自己焊盘里）
        free[l][i, j] = True
    path = astar(g, free, via_free, starts, goals)
    if not path:
        return False
    # 路径 → 走线段 + 过孔（合并共线点）
    pts = []
    for k, (l, i, j) in enumerate(path):
        x, y = g.xy(i, j)
        pts.append((l, x, y))
    segs, vias = [], []
    start = pts[0]
    prev = pts[0]
    prev_dir = None
    for cur in pts[1:]:
        if cur[0] != prev[0]:
            if (start[1], start[2]) != (prev[1], prev[2]):
                segs.append((start, prev))
            vias.append((prev[1], prev[2]))
            start, prev, prev_dir = cur, cur, None
            continue
        d = (round((cur[1] - prev[1]) / GRID), round((cur[2] - prev[2]) / GRID))
        if prev_dir is not None and d != prev_dir:
            segs.append((start, prev))
            start = prev
        prev_dir = d
        prev = cur
    if (start[1], start[2]) != (prev[1], prev[2]):
        segs.append((start, prev))
    for a, b in segs:
        t = pcbnew.PCB_TRACK(board)
        t.SetStart(pcbnew.VECTOR2I(pcbnew.FromMM(a[1]), pcbnew.FromMM(a[2])))
        t.SetEnd(pcbnew.VECTOR2I(pcbnew.FromMM(b[1]), pcbnew.FromMM(b[2])))
        t.SetWidth(pcbnew.FromMM(width))
        t.SetLayer(a[0])
        t.SetNet(net)
        board.Add(t)
    for x, y in vias:
        v = pcbnew.PCB_VIA(board)
        v.SetPosition(pcbnew.VECTOR2I(pcbnew.FromMM(x), pcbnew.FromMM(y)))
        v.SetWidth(pcbnew.FromMM(via_d))
        v.SetDrill(pcbnew.FromMM(via_drill))
        v.SetNet(net)
        board.Add(v)
    # 起点在焊盘中心到路径第一点的连接：路径第一点就在焊盘内，焊盘本身导通
    return True
