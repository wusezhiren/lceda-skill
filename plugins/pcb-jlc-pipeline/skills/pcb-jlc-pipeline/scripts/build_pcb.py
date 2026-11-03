"""
从 c3_switch_board.net 生成 c3_switch_board.kicad_pcb：放置封装、分配网络、画板框。
所有元件放顶层（F.Cu）。坐标单位 mm，原点为板左上角，x 向右、y 向下。

运行：kicad-cli sch export netlist -o build/sch.net c3_switch_board.kicad_sch
      python3 build_pcb.py      （用系统 python3，需要 KiCad 自带的 pcbnew 模块）
"""
# ==================== 按项目修改的部分 ====================
#   W, H                板尺寸（mm）
#   PLACE               位号 → (x, y, 旋转)；原点为板左上角，x 右 y 下
#   tidy_silkscreen()   功能标注文字（RST/BOOT/接口说明/背面排针定义）
#   main() 里的禁布区   模组本体（顶层禁走线/过孔）、天线整条（两层全禁）、
#                       Type-C 外壳下禁过孔 —— 引用了 U1 / J1 的坐标
#   write_project_rules() 里的网络类别：Power/Mid/GND/VBUS 的线宽与匹配的网络名
#                       （本地网络名带 "/" 前缀，如 "/VOUT1"；电源符号网络不带）
# 其余（读网表、放封装、关联原理图、板框）通用。
# ==========================================================


import os
import re

import pcbnew

HERE = os.path.dirname(os.path.abspath(__file__))
NET_FILE = os.path.join(HERE, "build", "sch.net")   # kicad-cli sch export netlist 生成
PCB_FILE = os.path.join(HERE, "c3_switch_board.kicad_pcb")
KICAD_FP = "/usr/share/kicad/footprints"

W, H = 33.5, 43.0          # 板尺寸
OX, OY = 100.0, 100.0      # 板左上角在 KiCad 坐标系里的位置

# 位号: (x, y, 旋转角度)
# 信号流：Type-C(右下) → F1 → +5V 主干横穿中部 → LDO / Q3 → USB-A(左下)
#         USB D+/D- 沿右侧通道上到模组 26/27 脚；通道 2 和 J3 在右侧中部
PLACE = {
    # 模组：天线朝上贴板边
    "U1": (15.0, 8.54, 0),
    # 安装孔
    "H1": (2.7, 2.7, 0),
    "H2": (27.0, 3.0, 0),
    # 扩展排针，沿左边
    "J4": (2.6, 7.1, 0),
    # 模组左侧：3V3 去耦、GPIO2 上拉、EN 阻容
    "C5": (6.3, 7.4, 90),
    "C6": (6.3, 10.0, 90),
    "R6": (6.3, 12.0, 90),
    "R4": (6.3, 14.0, 90),
    "C7": (6.3, 16.0, 90),
    # 底边：USB-A（左）+ Type-C（右），开口朝下
    "J2": (5.6, 30.0, 0),
    "J1": (24.3, 39.1, 0),
    # 右上：UART 测试点、RST / BOOT
    "TP1": (23.3, 8.0, 0),
    "TP2": (23.3, 10.4, 0),
    "SW1": (27.8, 8.6, 90),
    "SW2": (27.8, 14.9, 90),
    # 模组下方：GPIO7/8/9 相关电阻
    "R12": (17.2, 18.4, -90),
    "R7": (18.4, 18.4, 90),
    "R5": (24.5, 17.1, 0),        # GPIO9 上拉，挨着 BOOT 键
    # 状态灯紧挨 GPIO8，不跨 USB 数据线通道
    "D2": (21.0, 18.6, -90),      # 阴极朝上接 GPIO8，阳极朝下接 R8
    "R8": (21.0, 21.15, 90),
    # 右侧中部：通道 2 + 焊盘
    "J3": (27.9, 20.4, -90),
    # 右边新增一列：电源输出焊线盘 J5（自上而下 3V3 / GND / +5V）
    "J5": (31.8, 8.4, -90),
    "Q2": (24.5, 21.0, 90),
    "R13": (24.5, 18.3, 0),
    "D4": (24.5, 24.9, 90),
    "C9": (24.5, 27.4, 0),
    # 右下：F1 在左侧 VBUS 过孔正上方，U2 居中，CC1 从 F1/U2 之间上到 R1，R2 在右，外壳阻容在左
    "F1": (21.85, 31.0, 90),
    "U2": (25.0, 30.8, 90),
    "R1": (23.1, 27.6, 90),
    "R2": (28.4, 31.2, 90),
    "C1": (19.4, 30.4, 90),
    "R3": (19.4, 32.6, 90),
    # 中部偏左：LDO（与模组底边留 ≥1.5mm 通道，给 GPIO0/1/3 往左去排针）
    "U3": (6.8, 20.4, 0),
    "C3": (10.6, 19.8, 90),
    "C4": (12.2, 19.8, 90),
    # 左下：通道 1 高边开关（Q3 漏极朝下对着 USB-A 的 VBUS）
    "Q3": (6.4, 26.0, -90),
    "R17": (9.2, 23.6, 0),
    "C2": (10.5, 26.4, 0),
    "Q1": (15.0, 26.2, 0),
    "R10": (13.6, 21.4, 90),
    "R11": (15.0, 21.4, 90),
}


def mm(x, y):
    return pcbnew.VECTOR2I(pcbnew.FromMM(OX + x), pcbnew.FromMM(OY + y))


def parse_netlist(path):
    """解析 kicad-cli sch export netlist 导出的 KiCad 网表。"""
    s = open(path, encoding="utf-8").read()
    comps = {}
    comp_sec = s[s.find("(components"):s.find("(libparts")]
    for b in re.split(r"\(comp \(ref ", comp_sec)[1:]:
        ref = re.match(r'"([^"]+)"', b)[1]
        if ref.startswith("#"):
            continue
        comps[ref] = {
            "value": re.search(r'\(value "([^"]*)"', b)[1],
            "footprint": re.search(r'\(footprint "([^"]*)"', b)[1],
            "fields": dict(re.findall(r'\(field \(name "([^"]+)"\)\s*"([^"]*)"\)', b)),
            "props": set(re.findall(r'\(property \(name "([^"]+)"\)', b)),
            "uuid": re.findall(r'\(tstamps "([^"]+)"\)', b)[-1],
        }
    nets = {}
    net_sec = s[s.find("(nets"):]
    for m in re.finditer(r'\(net \(code "\d+"\) \(name "([^"]*)"\)(.*?)(?=\(net \(code|\Z)',
                         net_sec, re.S):
        nets[m.group(1)] = re.findall(r'\(node \(ref "([^"]+)"\) \(pin "([^"]+)"\)', m.group(2))
    return comps, nets


def fp_lib_path(lib):
    if lib == "PCM_Espressif":
        return os.path.join(HERE, "lib", "Espressif.pretty")
    return os.path.join(KICAD_FP, lib + ".pretty")


def main():
    comps, nets = parse_netlist(NET_FILE)
    board = pcbnew.BOARD()
    board.SetCopperLayerCount(2)

    # 网络
    netinfo = {}
    for name in nets:
        ni = pcbnew.NETINFO_ITEM(board, name)
        board.Add(ni)
        netinfo[name] = ni
    pad_net = {}
    for name, nodes in nets.items():
        for ref, pin in nodes:
            pad_net[(ref, pin)] = name

    # 封装
    missing = []
    for ref, c in sorted(comps.items()):
        lib, name = c["footprint"].split(":")
        fp = pcbnew.FootprintLoad(fp_lib_path(lib), name)
        fp.SetFPID(pcbnew.LIB_ID(lib, name))
        fp.SetReference(ref)
        fp.SetValue(c["value"])
        fp.SetPath(pcbnew.KIID_PATH("/" + c["uuid"]))   # 关联原理图符号
        # 封装属性与符号保持一致（测试点、安装孔封装默认带“从 BOM 排除”）
        attrs = fp.GetAttributes() & ~(pcbnew.FP_EXCLUDE_FROM_BOM | pcbnew.FP_EXCLUDE_FROM_POS_FILES)
        if "exclude_from_bom" in c["props"]:
            attrs |= pcbnew.FP_EXCLUDE_FROM_BOM
        fp.SetAttributes(attrs)
        for k, v in c["fields"].items():
            if k == "LCSC":
                fp.SetField("LCSC", v)
                fp.GetFieldByName("LCSC").SetVisible(False)   # 只做 BOM 用，不上丝印
        if ref not in PLACE:
            missing.append(ref)
            x, y, rot = W + 10, 10 + 5 * len(missing), 0
        else:
            x, y, rot = PLACE[ref]
        board.Add(fp)
        fp.SetPosition(mm(x, y))
        fp.SetOrientationDegrees(rot)
        for pad in fp.Pads():
            n = pad_net.get((ref, pad.GetNumber()))
            if n:
                pad.SetNet(netinfo[n])
    if missing:
        print("未放置:", missing)

    # 板框
    pts = [(0, 0), (W, 0), (W, H), (0, H)]
    for (x1, y1), (x2, y2) in zip(pts, pts[1:] + pts[:1]):
        seg = pcbnew.PCB_SHAPE(board)
        seg.SetShape(pcbnew.SHAPE_T_SEGMENT)
        seg.SetLayer(pcbnew.Edge_Cuts)
        seg.SetWidth(pcbnew.FromMM(0.1))
        seg.SetStart(mm(x1, y1))
        seg.SetEnd(mm(x2, y2))
        board.Add(seg)

    tidy_silkscreen(board)

    # 模组本体正下方：禁止顶层走线和过孔（底部是大片接地焊盘），底层走线允许
    ux, uy, _ = PLACE["U1"]
    ko = pcbnew.ZONE(board)
    ko.SetIsRuleArea(True)
    ko.SetDoNotAllowVias(True)
    ko.SetDoNotAllowTracks(True)
    ko.SetDoNotAllowCopperPour(False)
    ko.SetDoNotAllowPads(False)
    ko.SetDoNotAllowFootprints(False)
    ko.SetLayer(pcbnew.F_Cu)
    ko.SetZoneName("U1_body_keepout")
    ol = ko.Outline()
    ol.NewOutline()
    for dx, dy in [(-5.2, -3.1), (5.2, -3.1), (5.2, 7.0), (-5.2, 7.0)]:
        ol.Append(mm(ux + dx, uy + dy))
    board.Add(ko)

    # 天线区：板顶整条两层禁走线/过孔/铺铜（模组封装自带的禁布区只覆盖模组宽度）
    add_rule_area(board, "antenna_keepout", [(0, 0), (W, 0), (W, 5.7), (0, 5.7)],
                  layers=(pcbnew.F_Cu, pcbnew.B_Cu), tracks=True, vias=True, pour=True)
    # Type-C 外壳下方禁过孔（外壳接 SHIELD，不是 GND）
    jx, jy, _ = PLACE["J1"]
    add_rule_area(board, "usbc_shell_novia", [(jx - 4.5, jy - 3.0), (jx + 4.5, jy - 3.0),
                                              (jx + 4.5, H), (jx - 4.5, H)],
                  layers=(pcbnew.F_Cu, pcbnew.B_Cu), tracks=False, vias=True, pour=False)

    board.Save(PCB_FILE)
    write_project_rules()
    print("saved", PCB_FILE, len(comps), "footprints")


def add_text(board, text, x, y, layer=pcbnew.F_SilkS, h=0.8, angle=0, justify=None):
    t = pcbnew.PCB_TEXT(board)
    t.SetText(text)
    t.SetLayer(layer)
    t.SetTextSize(pcbnew.VECTOR2I(pcbnew.FromMM(h), pcbnew.FromMM(h)))
    t.SetTextThickness(pcbnew.FromMM(max(0.12, h * 0.15)))
    t.SetPosition(mm(x, y))
    t.SetTextAngleDegrees(angle)
    if layer == pcbnew.B_SilkS:
        t.SetMirrored(True)
    if justify == "left":
        t.SetHorizJustify(pcbnew.GR_TEXT_H_ALIGN_LEFT)
    elif justify == "right":
        t.SetHorizJustify(pcbnew.GR_TEXT_H_ALIGN_RIGHT)
    board.Add(t)
    return t


def tidy_silkscreen(board):
    """隐藏位号，加功能标注。"""
    for fp in board.GetFootprints():
        fp.Reference().SetVisible(False)
        # 连接器伸出板边的丝印不删（删了会与库不一致），嘉立创出图时会自动裁掉
    # 顶面：按键、通道 2 焊盘极性、USB-A 输出
    sx = PLACE["SW1"][0] - 2.6
    add_text(board, "RST", sx, PLACE["SW1"][1], h=0.7, angle=90)
    add_text(board, "BOOT", sx, PLACE["SW2"][1], h=0.7, angle=90)
    jx, jy, _ = PLACE["J3"]
    add_text(board, "5V+", jx, jy - 1.6, h=0.7)
    add_text(board, "OUT-", jx, jy + 4.6 + 1.6, h=0.7)
    ux, uy, _ = PLACE["J2"]
    add_text(board, "CH1 USB 5V/2A", ux + 3.5, uy - 2.25, h=0.7)
    # 背面：排针功能、板名
    px, py, _ = PLACE["J4"]
    for k, name in enumerate(["3V3", "GND", "IO0", "IO1", "IO3", "IO4", "IO5", "IO6"]):
        add_text(board, name, px + 1.6, py + 2.54 * k, layer=pcbnew.B_SilkS, h=0.8, justify="right")
    add_text(board, "ESP32-C3 SWITCH v1.1", W / 2 + 3, H - 1.6, layer=pcbnew.B_SilkS, h=1.0)
    add_text(board, "J3: CH2 <=0.5A", 26.0, 22.7, layer=pcbnew.B_SilkS, h=0.8, angle=90)
    # 电源输出焊盘 J5
    j5x, j5y, _ = PLACE["J5"]
    for k, name in enumerate(["3V3", "GND", "5V"]):
        add_text(board, name, j5x - 1.75, j5y + 4.6 * k, h=0.7, angle=90)
    add_text(board, "J5: 3V3 <=150mA", j5x - 2.1, j5y + 4.6, layer=pcbnew.B_SilkS, h=0.7, angle=90)


def add_rule_area(board, name, pts, layers, tracks, vias, pour):
    z = pcbnew.ZONE(board)
    z.SetIsRuleArea(True)
    z.SetZoneName(name)
    z.SetDoNotAllowTracks(tracks)
    z.SetDoNotAllowVias(vias)
    z.SetDoNotAllowCopperPour(pour)
    z.SetDoNotAllowPads(False)
    z.SetDoNotAllowFootprints(False)
    ls = pcbnew.LSET()
    for l in layers:
        ls.AddLayer(l)
    z.SetLayerSet(ls)
    ol = z.Outline()
    ol.NewOutline()
    for x, y in pts:
        ol.Append(mm(x, y))
    board.Add(z)
    return z


def write_project_rules():
    """线宽/过孔规则写入 .kicad_pro（board.Save 会重写工程文件，所以放在保存之后）。
    按嘉立创工艺：最小线宽/间距 0.15，过孔 0.3/0.5 起。"""
    import json
    pro_path = os.path.splitext(PCB_FILE)[0] + ".kicad_pro"
    pro = json.load(open(pro_path, encoding="utf-8"))

    def cls(name, width, via_d, via_drill, prio):
        return {"name": name, "bus_width": 12, "clearance": 0.2, "diff_pair_gap": 0.25,
                "diff_pair_via_gap": 0.25, "diff_pair_width": 0.2, "line_style": 0,
                "microvia_diameter": 0.3, "microvia_drill": 0.1,
                "pcb_color": "rgba(0, 0, 0, 0.000)", "priority": prio,
                "schematic_color": "rgba(0, 0, 0, 0.000)", "track_width": width,
                "via_diameter": via_d, "via_drill": via_drill, "wire_width": 6}

    ns = pro.setdefault("net_settings", {})
    ns["classes"] = [cls("Default", 0.25, 0.6, 0.3, 2147483647),
                     cls("Power", 0.8, 0.8, 0.4, 0),     # 2A 路径
                     cls("Mid", 0.4, 0.6, 0.3, 1),
                     cls("GND", 0.4, 0.6, 0.3, 2),       # 走铺铜 + 过孔，不参与自动布线
                     cls("VBUS", 0.5, 0.8, 0.4, 3)]      # Type-C→保险丝，仅约 5mm，口子窄
    ns["netclass_patterns"] = (
        [{"netclass": "Power", "pattern": p} for p in ("+5V", "/VOUT1")]
        + [{"netclass": "VBUS", "pattern": "VBUS"}]
        + [{"netclass": "Mid", "pattern": p} for p in ("+3V3", "/OUT2")]
        + [{"netclass": "GND", "pattern": "GND"}])
    rules = pro.setdefault("board", {}).setdefault("design_settings", {}).setdefault("rules", {})
    rules.update({"min_clearance": 0.15, "min_track_width": 0.15, "min_via_diameter": 0.5,
                  "min_via_annular_width": 0.1, "min_through_hole_diameter": 0.3,
                  "min_hole_to_hole": 0.25, "min_hole_clearance": 0.25,
                  "min_copper_edge_clearance": 0.3, "min_text_height": 0.6,
                  "min_text_thickness": 0.1})
    json.dump(pro, open(pro_path, "w", encoding="utf-8"), indent=2, ensure_ascii=False)


if __name__ == "__main__":
    main()
