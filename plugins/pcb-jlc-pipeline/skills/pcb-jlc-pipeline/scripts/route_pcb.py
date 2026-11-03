"""
自动布线：导出 Specctra DSN → Freerouting（跳过 GND）→ 导回 SES
         → GND 焊盘就近打过孔 → 两面铺 GND → 补缝合过孔 → 保存。
先运行 build_pcb.py 生成摆好件的 c3_switch_board.kicad_pcb。

运行：python3 route_pcb.py [布线遍数，默认 40]
      python3 route_pcb.py best [遍数...]   多种遍数各跑一次，保留最好的
需要：~/tools/jre（Java 21）、~/tools/freerouting/fr19.jar，
      以及显示环境（DISPLAY）或 xvfb-run —— Freerouting 1.9 必须有 X。
"""

import math
import os
import subprocess
import sys

import pcbnew

# ==================== 按项目修改的部分 ====================
#   GND_LINKS           去耦电容 → 芯片，布线前先把地就近连上（别连 SOT-23 LDO 中间的 GND 脚，会围死 IN/EN）
#   POWER_WIDEN         大电流网络 → 目标线宽（有空间才加宽）
#   HIGH_CURRENT_THT    大电流通孔连接器（GND 脚与铺铜全连接，不用花焊盘）
#   preroute_usb_c()    Type-C 位号 J1、焊盘 A6/B6/A7/B7（按封装朝向自动换算）；没有 Type-C 就删掉调用
#   preroute_vbus()     仅在 PREROUTE_VBUS=1 时启用（会挡住 D- 交叉，默认关）
#   stitch_gnd_pads()   跳过 U1 的 49~53 号底部焊盘（ESP32 MINI 模组专用）
# 其余（DSN/SES、Freerouting、迷宫补线、过孔/铺铜/孤岛）通用。
# ==========================================================

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

HERE = os.path.dirname(os.path.abspath(__file__))
PCB_FILE = os.path.join(HERE, "c3_switch_board.kicad_pcb")
WORK = os.path.join(HERE, "build")
JAVA = os.path.expanduser("~/tools/jre/bin/java")
FREEROUTING = os.path.expanduser("~/tools/freerouting/fr19.jar")
OX, OY = 100.0, 100.0

VIA_D, VIA_DRILL = 0.6, 0.3
CLEAR = 0.22              # 过孔/短线与其他网络的间距（规则 0.2，留余量）
STUB_W = 0.4
EDGE_KEEP = 0.6


def mm(x, y):
    return pcbnew.VECTOR2I(pcbnew.FromMM(OX + x), pcbnew.FromMM(OY + y))


def v2(x, y):
    """绝对坐标（mm）"""
    return pcbnew.VECTOR2I(pcbnew.FromMM(x), pcbnew.FromMM(y))


def to_mm(p):
    return pcbnew.ToMM(p.x), pcbnew.ToMM(p.y)


# ---------------------------------------------------------------- 障碍物检查
class Obstacles:
    """非 GND 铜皮：焊盘多边形 + 走线段 + 过孔，以及天线禁布区、板边。"""

    def __init__(self, board, gnd_code):
        self.pads = []      # (SHAPE_POLY_SET, layerset)
        self.segs = []      # (x1, y1, x2, y2, half_w, layer)
        self.vias = []      # (x, y, r)
        self.keepouts = []  # SHAPE_POLY_SET
        self.holes = []     # (x, y, r)  所有钻孔（含 GND），用于孔间距
        for fp in board.GetFootprints():
            for pad in fp.Pads():
                if pad.GetDrillSize().x > 0:
                    hx, hy = to_mm(pad.GetPosition())
                    self.holes.append((hx, hy, pcbnew.ToMM(max(pad.GetDrillSize().x, pad.GetDrillSize().y)) / 2))
                if pad.GetNetCode() == gnd_code:
                    continue
                for layer in (pcbnew.F_Cu, pcbnew.B_Cu):
                    if pad.IsOnLayer(layer):
                        poly = pcbnew.SHAPE_POLY_SET()
                        pad.TransformShapeToPolygon(poly, layer, 0, pcbnew.FromMM(0.005),
                                                    pcbnew.ERROR_INSIDE)
                        self.pads.append((poly, layer))
            for z in fp.Zones():
                if z.GetIsRuleArea():
                    self.keepouts.append(z.Outline())
        for z in board.Zones():
            if z.GetIsRuleArea() and z.GetDoNotAllowVias():
                self.keepouts.append(z.Outline())
        for t in board.GetTracks():
            if t.GetNetCode() == gnd_code and t.GetClass() != "PCB_VIA":
                continue           # GND 走线不算障碍；GND 过孔要算（孔间距）
            if t.GetClass() == "PCB_VIA":
                x, y = to_mm(t.GetPosition())
                self.vias.append((x, y, pcbnew.ToMM(t.GetWidth(pcbnew.F_Cu)) / 2))
            else:
                x1, y1 = to_mm(t.GetStart())
                x2, y2 = to_mm(t.GetEnd())
                self.segs.append((x1, y1, x2, y2, pcbnew.ToMM(t.GetWidth()) / 2, t.GetLayer()))
        bb = board.GetBoardEdgesBoundingBox()
        self.bx0, self.by0 = to_mm(bb.GetOrigin())
        self.bx1, self.by1 = to_mm(bb.GetEnd())

    @staticmethod
    def _seg_dist(px, py, x1, y1, x2, y2):
        dx, dy = x2 - x1, y2 - y1
        L2 = dx * dx + dy * dy
        t = 0 if L2 == 0 else max(0, min(1, ((px - x1) * dx + (py - y1) * dy) / L2))
        return math.hypot(px - (x1 + t * dx), py - (y1 + t * dy))

    def circle_free(self, x, y, r, layers, ignore_keepout=False):
        if not (self.bx0 + EDGE_KEEP + r <= x <= self.bx1 - EDGE_KEEP - r
                and self.by0 + EDGE_KEEP + r <= y <= self.by1 - EDGE_KEEP - r):
            return False
        p = v2(x, y)
        for ko in ([] if ignore_keepout else self.keepouts):
            if ko.Collide(p, pcbnew.FromMM(r)):
                return False
        for poly, layer in self.pads:
            if layer in layers and poly.Collide(p, pcbnew.FromMM(r + CLEAR)):
                return False
        for x1, y1, x2, y2, hw, layer in self.segs:
            if layer in layers and self._seg_dist(x, y, x1, y1, x2, y2) < r + hw + CLEAR:
                return False
        for vx, vy, vr in self.vias:
            if math.hypot(x - vx, y - vy) < r + vr + CLEAR:
                return False
        if r >= VIA_D / 2 - 1e-6:          # 放过孔时检查孔间距（规则 0.25，留余量）
            for hx, hy, hr in self.holes:
                if math.hypot(x - hx, y - hy) < VIA_DRILL / 2 + hr + 0.3:
                    return False
        return True

    def segment_free(self, x1, y1, x2, y2, hw, layer):
        n = max(2, int(math.hypot(x2 - x1, y2 - y1) / 0.08))
        for i in range(n + 1):
            t = i / n
            if not self.circle_free(x1 + t * (x2 - x1), y1 + t * (y2 - y1), hw, (layer,)):
                return False
        return True

    def add_via(self, x, y, r):
        self.vias.append((x, y, r))


def add_via(board, net, x, y, d=VIA_D, drill=VIA_DRILL):
    via = pcbnew.PCB_VIA(board)
    via.SetPosition(v2(x, y))
    via.SetWidth(pcbnew.FromMM(d))
    via.SetDrill(pcbnew.FromMM(drill))
    via.SetNet(net)
    board.Add(via)
    return via


def add_track(board, net, x1, y1, x2, y2, w, layer=pcbnew.F_Cu):
    t = pcbnew.PCB_TRACK(board)
    t.SetStart(v2(x1, y1))
    t.SetEnd(v2(x2, y2))
    t.SetWidth(pcbnew.FromMM(w))
    t.SetLayer(layer)
    t.SetNet(net)
    board.Add(t)
    return t


def stitch_gnd_pads(board):
    """每个顶层 GND 贴片焊盘旁边找空位打过孔，短线连过去。"""
    gnd = board.FindNet("GND")
    obs = Obstacles(board, gnd.GetNetCode())
    r = VIA_D / 2
    done, failed = 0, []
    u1 = board.FindFootprintByReference("U1")
    for fp in board.GetFootprints():
        for pad in fp.Pads():
            if pad.GetNetCode() != gnd.GetNetCode():
                continue
            if pad.GetAttribute() != pcbnew.PAD_ATTRIB_SMD:
                continue           # 通孔焊盘本身就连两层
            if fp.GetReference() == "U1" and pad.GetNumber() in ("49", "50", "51", "52", "53"):
                continue           # 模组底部焊盘：中心阵列单独打孔，四角小焊盘靠铺铜
            px, py = to_mm(pad.GetPosition())
            sx, sy = to_mm(pad.GetSize())
            reach = max(sx, sy) / 2
            best = None
            for d in [reach + r + 0.15 + 0.2 * i for i in range(14)]:
                for k in range(24):
                    a = 2 * math.pi * k / 24
                    vx, vy = px + d * math.cos(a), py + d * math.sin(a)
                    if not obs.circle_free(vx, vy, r, (pcbnew.F_Cu, pcbnew.B_Cu)):
                        continue
                    if not obs.segment_free(px, py, vx, vy, STUB_W / 2, pcbnew.F_Cu):
                        continue
                    best = (vx, vy)
                    break
                if best:
                    break
            if best:
                add_via(board, gnd, *best)
                add_track(board, gnd, px, py, best[0], best[1], STUB_W)
                obs.add_via(best[0], best[1], r)
                done += 1
            else:
                failed.append(f"{fp.GetReference()}.{pad.GetNumber()}")
    # 模组中心接地焊盘阵列（焊盘 49）落在模组本体禁布区内，不打孔；
    # 由顶层铺铜（全连接）接到模组四周 GND 脚和外圈过孔
    if False and u1:
        ux, uy = to_mm(u1.GetPosition())
        for dx, dy in ((-0.9875, 1.7125), (0.9875, 1.7125), (-0.9875, 3.6875), (0.9875, 3.6875)):
            # 只查底层：顶层是同网络的焊盘 49；底层可能有走线从模组下方穿过
            if obs.circle_free(ux + dx, uy + dy, r, (pcbnew.B_Cu,), ignore_keepout=True):
                add_via(board, gnd, ux + dx, uy + dy)
                obs.add_via(ux + dx, uy + dy, r)
                done += 1
    print(f"GND 焊盘过孔 {done} 个；找不到位置: {failed}")


def preroute_vbus(board):
    """Type-C 两组 VBUS 焊盘（A4/B9 与 A9/B4）在焊盘上方各打一个过孔，底层 0.5mm 相连。
    Type-C 上方空间窄，交给自动布线常常只连上一组。预布线锁定，Freerouting 不会改。"""
    j1 = board.FindFootprintByReference("J1")
    vbus = board.FindNet("VBUS")
    pts = []
    for num in ("A4", "A9"):
        pad = next(p for p in j1.Pads() if p.GetNumber() == num)
        px, py = to_mm(pad.GetPosition())
        top = py - pcbnew.ToMM(pad.GetSize().y) / 2
        vy = top - 0.4 - 0.05              # 过孔紧贴焊盘上沿（同网络）
        add_track(board, vbus, px, py, px, vy, 0.5).SetLocked(True)
        v = add_via(board, vbus, px, vy, d=0.8, drill=0.4)
        v.SetLocked(True)
        pts.append((px, vy))
    add_track(board, vbus, pts[0][0], pts[0][1], pts[1][0], pts[1][1], 0.5,
              pcbnew.B_Cu).SetLocked(True)
    # 左侧过孔 → 保险丝 F1 输入焊盘
    f1 = board.FindFootprintByReference("F1")
    fpad = min((p for p in f1.Pads() if p.GetNetname() == "VBUS"),
               key=lambda p: abs(pcbnew.ToMM(p.GetPosition().y) - pts[0][1]))
    fx, fy = to_mm(fpad.GetPosition())
    add_track(board, vbus, pts[0][0], pts[0][1], fx, fy, 0.8).SetLocked(True)


def preroute_usb_c(board, w=0.2, gap=0.45):
    """Type-C 的 D+/D- 两面焊盘交错（B7 D-、A6 D+、A7 D-、B6 D+），自动布线常连不全。
    D+（A6↔B6）在焊盘下方用 U 形线连，D-（B7↔A7）在焊盘上方用 U 形线连，互不交叉。"""
    j1 = board.FindFootprintByReference("J1")
    pad = {p.GetNumber(): p for p in j1.Pads()}
    # “下方/上方”按封装自身坐标（+y 朝插口），再按封装旋转角换到板坐标，任意朝向都适用
    a = math.radians(j1.GetOrientationDegrees())
    ux, uy = math.sin(a), math.cos(a)            # 封装 +y 方向在板上的单位向量
    for (n1, n2, below) in (("A6", "B6", True), ("B7", "A7", False)):
        p1, p2 = pad[n1], pad[n2]
        net = p1.GetNet()
        (x1, y1), (x2, y2) = to_mm(p1.GetPosition()), to_mm(p2.GetPosition())
        d = (pcbnew.ToMM(p1.GetSize().y) / 2 + gap) * (1 if below else -1)
        a1, a2 = (x1 + ux * d, y1 + uy * d), (x2 + ux * d, y2 + uy * d)
        for (ax, ay), (bx, by) in (((x1, y1), a1), (a1, a2), (a2, (x2, y2))):
            add_track(board, net, ax, ay, bx, by, w).SetLocked(True)


HIGH_CURRENT_THT = ("J2",)     # 大电流通孔连接器，GND 焊盘与铺铜全连接
POWER_WIDEN = {"+5V": 1.2, "/VOUT1": 1.2, "VBUS": 0.8}


def widen_power(board, nets=POWER_WIDEN):
    """大电流网络：周围有空间的走线段加宽，没空间的保持原样。"""
    n = 0
    for name, width in nets.items():
        net = board.FindNet(name)
        if not net:
            continue
        obs = Obstacles(board, net.GetNetCode())
        for t in board.GetTracks():
            if t.GetNetCode() != net.GetNetCode() or t.GetClass() == "PCB_VIA":
                continue
            if pcbnew.ToMM(t.GetWidth()) >= width:
                continue
            x1, y1 = to_mm(t.GetStart())
            x2, y2 = to_mm(t.GetEnd())
            if obs.segment_free(x1, y1, x2, y2, width / 2, t.GetLayer()):
                t.SetWidth(pcbnew.FromMM(width))
                n += 1
    print(f"电源线加宽 {n} 段")


# 去耦电容的地先就近连到芯片 GND 脚（布线前做，锁定），避免后面被信号线围成孤岛
GND_LINKS = [("C5", "U1"), ("C6", "U1"), ("C7", "U1"), ("U2", "J1")]   # 别给 SOT-23 LDO 的中间 GND 脚预布：会把两侧 IN/EN 脚围死


def preroute_gnd_links(board, links=GND_LINKS, width=0.4):
    import maze
    gnd = board.FindNet("GND")
    for cap, chip in links:
        cpad = next(p for p in board.FindFootprintByReference(cap).Pads() if p.GetNetCode() == gnd.GetNetCode())
        cands = sorted((p for p in board.FindFootprintByReference(chip).Pads()
                        if p.GetNetCode() == gnd.GetNetCode() and p.GetAttribute() == pcbnew.PAD_ATTRIB_SMD),
                       key=lambda p: (p.GetPosition() - cpad.GetPosition()).EuclideanNorm())
        before = {t.m_Uuid.AsString() for t in board.GetTracks()}
        for target in cands[:4]:
            if maze.route_connection(board, cpad, target, width=width):
                for t in board.GetTracks():
                    if t.m_Uuid.AsString() not in before:
                        t.SetLocked(True)
                print(f"去耦地线: {cap} → {chip}.{target.GetNumber()}")
                break
        else:
            print(f"去耦地线失败: {cap} → {chip}")


def protect_gnd_tracks(board, margin=0.25):
    """Freerouting 用 -inc GND 跳过 GND 后，也不再把 GND 走线当障碍（会压上去短路）。
    导出 DSN 前给每段 GND 走线/过孔套一个临时禁布区，布完删除。返回这些禁布区。"""
    gnd = board.FindNet("GND").GetNetCode()
    tmp = []
    for t in list(board.GetTracks()):
        if t.GetNetCode() != gnd:
            continue
        x1, y1 = to_mm(t.GetStart())
        x2, y2 = to_mm(t.GetEnd())
        r = (pcbnew.ToMM(t.GetWidth(pcbnew.F_Cu)) if t.GetClass() == "PCB_VIA" else pcbnew.ToMM(t.GetWidth())) / 2 + margin
        dx, dy = x2 - x1, y2 - y1
        L = math.hypot(dx, dy) or 1e-9
        ux, uy = dx / L, dy / L
        nx, ny = -uy * r, ux * r
        ex, ey = ux * r, uy * r
        pts = [(x1 - ex + nx, y1 - ey + ny), (x2 + ex + nx, y2 + ey + ny),
               (x2 + ex - nx, y2 + ey - ny), (x1 - ex - nx, y1 - ey - ny)]
        z = pcbnew.ZONE(board)
        z.SetIsRuleArea(True)
        z.SetZoneName("tmp_gnd_guard")
        z.SetDoNotAllowTracks(True)
        z.SetDoNotAllowVias(True)
        z.SetDoNotAllowCopperPour(False)
        z.SetDoNotAllowPads(False)
        z.SetDoNotAllowFootprints(False)
        ls = pcbnew.LSET()
        if t.GetClass() == "PCB_VIA":
            ls.AddLayer(pcbnew.F_Cu)
            ls.AddLayer(pcbnew.B_Cu)
        else:
            ls.AddLayer(t.GetLayer())
        z.SetLayerSet(ls)
        ol = z.Outline()
        ol.NewOutline()
        for x, y in pts:
            ol.Append(v2(x, y))
        board.Add(z)
        tmp.append(z)
    return tmp


def add_gnd_zone(board, layer, w, h):
    gnd = board.FindNet("GND")
    z = pcbnew.ZONE(board)
    z.SetLayer(layer)
    z.SetNet(gnd)
    z.SetLocalClearance(pcbnew.FromMM(0.25))
    z.SetMinThickness(pcbnew.FromMM(0.2))
    z.SetPadConnection(pcbnew.ZONE_CONNECTION_FULL)     # 贴片焊盘全连接（回流焊）
    z.SetThermalReliefGap(pcbnew.FromMM(0.25))
    z.SetThermalReliefSpokeWidth(pcbnew.FromMM(0.4))
    z.SetIslandRemovalMode(pcbnew.ISLAND_REMOVAL_MODE_ALWAYS)
    outline = z.Outline()
    outline.NewOutline()
    for x, y in [(0, 0), (w, 0), (w, h), (0, h)]:
        outline.Append(mm(x, y))
    board.Add(z)
    return z


def stitch_grid(board, zones, pitch=2.5):
    """两面 GND 铺铜都覆盖的地方，按网格补缝合过孔。"""
    gnd = board.FindNet("GND")
    obs = Obstacles(board, gnd.GetNetCode())
    fpoly = zones[0].GetFilledPolysList(pcbnew.F_Cu)
    bpoly = zones[1].GetFilledPolysList(pcbnew.B_Cu)
    r = VIA_D / 2
    bb = board.GetBoardEdgesBoundingBox()
    x0, y0 = to_mm(bb.GetOrigin())
    x1, y1 = to_mm(bb.GetEnd())
    n = 0
    y = y0 + 1.5
    while y < y1 - 1.0:
        x = x0 + 1.5
        while x < x1 - 1.0:
            ok = obs.circle_free(x, y, r, (pcbnew.F_Cu, pcbnew.B_Cu))
            if ok:
                for a in range(8):
                    p = v2(x + 0.45 * math.cos(a * math.pi / 4), y + 0.45 * math.sin(a * math.pi / 4))
                    if not (fpoly.Contains(p) and bpoly.Contains(p)):
                        ok = False
                        break
            if ok:
                add_via(board, gnd, x, y)
                obs.add_via(x, y, r)
                n += 1
            x += pitch
        y += pitch
    print(f"缝合过孔 {n} 个")


def fix_islands(board, zones, rounds=3):
    """铺铜碎片里如果没有 GND 过孔/通孔焊盘，就在碎片内部找空位补一个过孔。"""
    gnd = board.FindNet("GND")
    filler = pcbnew.ZONE_FILLER(board)
    r = VIA_D / 2
    for _ in range(rounds):
        obs = Obstacles(board, gnd.GetNetCode())
        anchors = [t.GetPosition() for t in board.GetTracks()
                   if t.GetClass() == "PCB_VIA" and t.GetNetCode() == gnd.GetNetCode()]
        anchors += [p.GetPosition() for fp in board.GetFootprints() for p in fp.Pads()
                    if p.GetNetCode() == gnd.GetNetCode() and p.GetAttribute() == pcbnew.PAD_ATTRIB_PTH]
        fpoly = zones[0].GetFilledPolysList(pcbnew.F_Cu)
        bpoly = zones[1].GetFilledPolysList(pcbnew.B_Cu)
        added = 0
        for poly, other in ((fpoly, bpoly), (bpoly, fpoly)):
            for i in range(poly.OutlineCount()):
                ol = poly.Outline(i)
                if any(ol.PointInside(a) for a in anchors):
                    continue
                bb = ol.BBox()
                x0, y0 = to_mm(bb.GetOrigin())
                x1, y1 = to_mm(bb.GetEnd())
                found = None
                # 过孔只要和碎片重叠（铜接上）且离其他网络够远即可；底层铺铜会绕着它铺
                y = y0 - r
                while y < y1 + r and not found:
                    x = x0 - r
                    while x < x1 + r:
                        q = v2(x, y)
                        if ((ol.PointInside(q) or ol.Collide(q, pcbnew.FromMM(r - 0.08)))
                                and obs.circle_free(x, y, r, (pcbnew.F_Cu, pcbnew.B_Cu))):
                            found = (x, y)
                            break
                        x += 0.1
                    y += 0.1
                if found:
                    add_via(board, gnd, *found)
                    obs.add_via(found[0], found[1], r)
                    anchors.append(v2(*found))
                    added += 1
                elif route_island(board, ol, gnd):
                    added += 1
        added += join_clusters(board, zones)      # 碎片里有过孔、但整群与主地不通的情况
        filler.Fill(board.Zones())
        print(f"孤岛补孔 {added} 个")
        if not added:
            break


def gnd_clusters(board, zones):
    """把两层 GND 填充碎片按 过孔/通孔焊盘 连成群，返回 (frags, clusters, main_idx)。
    frags[i] = (layer, outline)；clusters = [[frag_idx...]...]；main = 面积最大的群。"""
    gnd = board.FindNet("GND").GetNetCode()
    frags = []
    for z in zones:
        L = z.GetLayer()
        poly = z.GetFilledPolysList(L)
        for i in range(poly.OutlineCount()):
            frags.append((L, poly.Outline(i)))
    parent = list(range(len(frags)))

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    links = [t.GetPosition() for t in board.GetTracks() if t.GetClass() == "PCB_VIA" and t.GetNetCode() == gnd]
    links += [p.GetPosition() for fp in board.GetFootprints() for p in fp.Pads()
              if p.GetNetCode() == gnd and p.GetAttribute() == pcbnew.PAD_ATTRIB_PTH]
    for pos in links:
        hit = [k for k, (_, ol) in enumerate(frags) if ol.PointInside(pos)]
        for k in hit[1:]:
            parent[find(k)] = find(hit[0])
    groups = {}
    for k in range(len(frags)):
        groups.setdefault(find(k), []).append(k)
    clusters = list(groups.values())
    main = max(range(len(clusters)), key=lambda c: sum(frags[k][1].Area() for k in clusters[c]))
    return frags, clusters, main


def join_clusters(board, zones):
    """把与主地不连通的 GND 群接回主地：先找“本群碎片 ∩ 另一层主地碎片”处补过孔，不行再迷宫连线。"""
    gnd = board.FindNet("GND")
    r = VIA_D / 2
    frags, clusters, main = gnd_clusters(board, zones)
    if len(clusters) <= 1:
        return 0
    obs = Obstacles(board, gnd.GetNetCode())
    main_frags = [frags[k] for k in clusters[main]]
    fixed = 0
    for ci, cl in enumerate(clusters):
        if ci == main:
            continue
        done = False
        for k in cl:
            L, ol = frags[k]
            others = [mol for (ML, mol) in main_frags if ML != L]
            bb = ol.BBox()
            x0, y0 = to_mm(bb.GetOrigin())
            x1, y1 = to_mm(bb.GetEnd())
            y = y0
            while y <= y1 and not done:
                x = x0
                while x <= x1:
                    q = v2(x, y)
                    if (ol.PointInside(q) and any(m.PointInside(q) for m in others)
                            and obs.circle_free(x, y, r, (pcbnew.F_Cu, pcbnew.B_Cu))):
                        add_via(board, gnd, x, y)
                        obs.add_via(x, y, r)
                        done = True
                        break
                    x += 0.1
                y += 0.1
            if done:
                break
        if not done:
            for k in cl:
                if route_island(board, frags[k][1], gnd):
                    done = True
                    break
        fixed += done
        print(f"GND 孤立群 {ci}（{len(cl)} 块碎片）: {'已接回主地' if done else '未能接回'}")
    return fixed


def route_island(board, ol, gnd):
    """碎片里放不下过孔时：把碎片内的 GND 焊盘用迷宫布线连到最近的 GND 过孔。"""
    import maze
    pads = [p for fp in board.GetFootprints() for p in fp.Pads()
            if p.GetNetCode() == gnd.GetNetCode() and ol.PointInside(p.GetPosition())]
    targets = [t for t in board.GetTracks() if t.GetClass() == "PCB_VIA" and t.GetNetCode() == gnd.GetNetCode()]
    targets += [p for fp in board.GetFootprints() for p in fp.Pads()
                if p.GetNetCode() == gnd.GetNetCode() and not ol.PointInside(p.GetPosition())]
    for pad in pads:
        for t in sorted(targets, key=lambda t: (t.GetPosition() - pad.GetPosition()).EuclideanNorm())[:12]:
            if maze.route_connection(board, pad, t, width=0.3):
                what = (f"{t.GetParentFootprint().GetReference()}.{t.GetNumber()}"
                        if isinstance(t, pcbnew.PAD) else "GND 过孔")
                print(f"孤岛连线: {pad.GetParentFootprint().GetReference()}.{pad.GetNumber()} → {what}")
                return True
    return False


def fix_unrouted(board, report_json):
    """读 DRC JSON 里的未连接项（GND 除外，GND 靠铺铜），用迷宫布线补线。"""
    import json
    import maze
    rep = json.load(open(report_json, encoding="utf-8"))
    fixed, failed = 0, []
    for u in rep.get("unconnected_items", []):
        items = [board.GetItem(pcbnew.KIID(it["uuid"])) for it in u["items"]]
        if len(items) != 2 or any(i is None or i.Type() == pcbnew.PCB_ZONE_T for i in items):
            continue
        items = [i.Cast() if hasattr(i, "Cast") else i for i in items]
        if items[0].GetNetname() == "GND":
            continue
        cls = items[0].GetNet().GetNetClassName()
        w = {"Power": 0.8, "VBUS": 0.5, "Mid": 0.4}.get(cls, 0.25)
        desc = " ↔ ".join(it["description"] for it in u["items"])
        ok = maze.route_connection(board, items[0], items[1], width=w)
        if not ok and w > 0.25:
            ok = maze.route_connection(board, items[0], items[1], width=0.25)
        if ok:
            fixed += 1
            print("迷宫补线:", desc)
        else:
            failed.append(desc)
    for d in failed:
        print("补线失败:", d)
    return fixed


def main():
    passes = sys.argv[1] if len(sys.argv) > 1 else "40"
    os.makedirs(WORK, exist_ok=True)
    dsn = os.path.join(WORK, "c3.dsn")
    ses = os.path.join(WORK, "c3.ses")

    board = pcbnew.LoadBoard(PCB_FILE)
    # 清掉旧的走线和铺铜，重新布
    for t in list(board.GetTracks()):
        board.Remove(t)
    for z in list(board.Zones()):
        if not z.GetIsRuleArea():      # 只清铺铜，保留禁布区
            board.Remove(z)
    preroute_usb_c(board)
    preroute_gnd_links(board)
    if os.environ.get("PREROUTE_VBUS"):
        preroute_vbus(board)
    guards = protect_gnd_tracks(board)
    if not pcbnew.ExportSpecctraDSN(board, dsn):
        sys.exit("DSN 导出失败")
    for z in guards:
        board.Remove(z)

    if os.path.exists(ses):
        os.remove(ses)
    cmd = ([] if os.environ.get("DISPLAY") else ["xvfb-run", "-a"]) + [
        JAVA, "-jar", FREEROUTING, "-de", dsn, "-do", ses, "-mp", passes,
        "-inc", "GND", "-dct", "0"]
    print(" ".join(cmd))
    subprocess.run(cmd, cwd=WORK, timeout=1800)
    if not os.path.exists(ses):
        sys.exit("Freerouting 没有输出 SES")
    if not pcbnew.ImportSpecctraSES(board, ses):
        sys.exit("SES 导入失败")
    board.Save(PCB_FILE)
    rpt = os.path.join(WORK, "drc.json")
    for _ in range(2):
        subprocess.run(["kicad-cli", "pcb", "drc", "--format", "json", "-o", rpt, PCB_FILE],
                       capture_output=True)
        board = pcbnew.LoadBoard(PCB_FILE)
        if not fix_unrouted(board, rpt):
            break
        board.Save(PCB_FILE)

    widen_power(board)
    stitch_gnd_pads(board)
    # 通孔 GND 焊盘（USB-A 固定脚、排针）用花焊盘，方便手焊
    for fp in board.GetFootprints():
        for pad in fp.Pads():
            if pad.GetNetname() == "GND" and pad.GetAttribute() == pcbnew.PAD_ATTRIB_PTH:
                # USB-A 的 GND 是 2A 回流路径，全连接；其余（排针）花焊盘
                conn = (pcbnew.ZONE_CONNECTION_FULL if fp.GetReference() in HIGH_CURRENT_THT
                        else pcbnew.ZONE_CONNECTION_THERMAL)
                pad.SetLocalZoneConnection(conn)

    bb = board.GetBoardEdgesBoundingBox()
    w, h = pcbnew.ToMM(bb.GetWidth()), pcbnew.ToMM(bb.GetHeight())
    zones = [add_gnd_zone(board, pcbnew.F_Cu, w, h), add_gnd_zone(board, pcbnew.B_Cu, w, h)]
    filler = pcbnew.ZONE_FILLER(board)
    filler.Fill(board.Zones())
    stitch_grid(board, zones)
    filler.Fill(board.Zones())
    fix_islands(board, zones)
    dedupe_vias(board)
    board.Save(PCB_FILE)
    print("saved", PCB_FILE)


def dedupe_vias(board):
    """迷宫补线/孤岛修补可能在同一点重复打孔（DRC 报 holes_co_located），保留一个。"""
    seen, n = set(), 0
    for t in list(board.GetTracks()):
        if t.GetClass() != "PCB_VIA":
            continue
        k = (t.GetPosition().x, t.GetPosition().y)
        if k in seen:
            board.Remove(t)
            n += 1
        else:
            seen.add(k)
    if n:
        print(f"删除重复过孔 {n} 个")


def count_problems(pcb):
    """返回 (未连接数, 错误级违规数)，用 kicad-cli DRC 评估一次布线结果。"""
    import json
    rpt = os.path.join(WORK, "eval.json")
    subprocess.run(["kicad-cli", "pcb", "drc", "--format", "json", "--severity-error", "-o", rpt, pcb],
                   capture_output=True)
    d = json.load(open(rpt, encoding="utf-8"))
    errs = [v for v in d["violations"] if not v["type"].startswith("silk")]
    return len(d["unconnected_items"]), len(errs)


def route_best(pass_list):
    """不同布线遍数各跑一次，保留未连接 + 违规最少的结果。"""
    import shutil
    base = os.path.join(WORK, "placed.kicad_pcb")
    shutil.copy(PCB_FILE, base)
    best = None
    for mp in pass_list:
        shutil.copy(base, PCB_FILE)
        sys.argv = [sys.argv[0], str(mp)]
        main()
        score = count_problems(PCB_FILE)
        print(f"== 遍数 {mp}: 未连接 {score[0]}，违规 {score[1]}")
        if best is None or score < best[0]:
            best = (score, mp)
            shutil.copy(PCB_FILE, os.path.join(WORK, "best.kicad_pcb"))
        if score == (0, 0):
            break
    shutil.copy(os.path.join(WORK, "best.kicad_pcb"), PCB_FILE)
    print(f"选用遍数 {best[1]}：未连接 {best[0][0]}，违规 {best[0][1]}")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "best":
        route_best([int(x) for x in (sys.argv[2:] or ["30", "50", "70", "90", "110", "150"])])
    else:
        main()
