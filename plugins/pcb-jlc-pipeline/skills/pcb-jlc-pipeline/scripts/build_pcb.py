"""
从 c3_switch_board.net 生成 c3_switch_board.kicad_pcb：放置封装、分配网络、画板框。
所有元件放顶层（F.Cu）。坐标单位 mm，原点为板左上角，x 向右、y 向下。

运行：kicad-cli sch export netlist -o build/sch.net c3_switch_board.kicad_sch
      python3 build_pcb.py      （用系统 python3，需要 KiCad 自带的 pcbnew 模块）
"""

import os
import re

import pcbnew

HERE = os.path.dirname(os.path.abspath(__file__))
NET_FILE = os.path.join(HERE, "build", "sch.net")   # kicad-cli sch export netlist 生成
PCB_FILE = os.path.join(HERE, "c3_switch_board.kicad_pcb")
KICAD_FP = "/usr/share/kicad/footprints"

# ==================== 按项目修改的部分 ====================
#   W, H                板尺寸（mm）
#   PLACE               位号 → (x, y, 旋转)；原点为板左上角，x 右 y 下
#   tidy_silkscreen()   功能标注文字（RST/BOOT/接口说明/背面排针定义）
#   main() 里的禁布区   模组本体（顶层禁走线/过孔）、天线带（模组宽度两侧各 +3mm，两层全禁）、
#                       Type-C 外壳下禁过孔 —— 引用了 U1 / J1 的坐标
#   write_project_rules() 里的网络类别：Power/Mid/GND/VBUS 的线宽与匹配的网络名
#                       （本地网络名带 "/" 前缀，如 "/VOUT1"；电源符号网络不带）
#   EXTRA               板上附加件（焊盘/测试点），只改 PCB 不动原理图
# 其余（读网表、放封装、关联原理图、板框）通用。
# ==========================================================

W, H = 55.4, 22.0          # 板尺寸：长条形，两端各一个口
OX, OY = 100.0, 100.0      # 板左上角在 KiCad 坐标系里的位置

# 位号: (x, y, 旋转角度)
# 长条布局：Type-C 在右端（插口朝右）、USB-A 在左端（插口朝左），模组居中、天线朝上贴长边。
# 信号流：J1 → F1 → +5V 从右往左（底层穿过模组下方）→ LDO（模组左侧）/ Q3 → USB-A。
#         USB D+/D-、UART 都在模组右侧，直接接右边的 Type-C 区。
PLACE = {
    # 模组：天线朝上贴板边
    "U1": (28.8, 8.54, 0),
    # 安装孔：天线两侧（无铜 NPTH，建议尼龙螺丝）
    "H1": (17.2, 2.6, 0),
    "H2": (40.4, 2.6, 0),
    # 左端：USB-A（插口朝左），上方一条放高边开关
    "J2": (13.0, 9.5, -90),
    "Q3": (12.6, 2.05, -90),     # 漏极朝下对着 USB-A 的 VBUS 脚
    "R17": (10.0, 2.05, 90),
    "Q1": (7.2, 2.05, 0),        # 漏极朝右接 Q3 栅极
    "R10": (4.2, 1.2, 0),
    "R11": (4.2, 2.9, 0),
    # USB-A 与模组之间：LDO + 大电容
    "U3": (16.9, 8.0, 0),        # OUT 脚在右上，挨着 C5
    "C3": (16.9, 11.0, 0),
    "C4": (16.9, 12.8, 0),
    "C2": (16.2, 16.3, 90),
    # 模组左侧一列：3V3 去耦、GPIO2 上拉、EN 阻容
    "C5": (20.1, 7.4, 90),
    "C6": (20.1, 10.0, 90),
    "R6": (20.1, 12.0, 90),
    "R4": (20.1, 14.0, 90),
    "C7": (20.1, 16.0, 90),
    # 模组下方：扩展排针横放（3V3 GND IO0 IO1 IO3 IO4 IO5 IO6，从左到右）
    "J4": (19.4, 20.1, 90),
    # 模组右侧一列：UART 测试点、GPIO8 灯、GPIO9 上拉
    "TP1": (37.4, 7.0, 0),
    "TP2": (37.4, 9.3, 0),
    "R7": (37.3, 11.3, 0),
    "D2": (37.3, 13.0, 0),
    "R8": (37.3, 14.7, 0),
    "R5": (37.3, 16.2, 0),
    # 右上：BOOT / RST 按键（天线禁布带右侧）
    "SW2": (46.0, 2.5, 0),
    "SW1": (52.1, 2.5, 0),
    # Type-C 内侧一列：RGB、ESD、CC 电阻、保险丝
    "D5": (41.2, 6.6, 0),
    "R18": (44.4, 5.9, 90),
    "C11": (44.4, 8.1, 90),
    "U2": (41.3, 11.2, 90),
    "R2": (44.4, 10.2, 90),
    "R1": (44.4, 12.4, 90),
    "F1": (42.3, 15.6, 0),
    # 右端：Type-C（插口朝右），下方外壳阻容
    "J1": (51.4, 11.0, 90),
    "C1": (48.2, 17.45, 0),
    "R3": (50.6, 17.45, 0),
    # 右下：电源输出焊线盘 J5（从左到右 3V3 / GND / +5V）
    "J5": (42.4, 20.2, 0),
}

# 板上附加件（不进原理图）：焊盘、测试点、安装孔等。只改 PCB，原理图不用动：
#   改完运行 pipeline.py --from build。标记为“仅板上”(Not in schematic)，一致性检查跳过，不进 BOM/坐标。
#   nets: 焊盘号 → 已有网络名（本地网络带 "/" 前缀，如 "/OUT2"；电源网络 "+5V"、"GND" 不带）
# 例：EXTRA = [{"ref": "TP10", "footprint": "TestPoint:TestPoint_Pad_D1.5mm", "at": (5, 30, 0),
#               "nets": {"1": "+5V"}, "label": "5V"}]
EXTRA = []


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
    # 板上附加件（不在原理图里）
    for e in EXTRA:
        lib, name = e["footprint"].split(":")
        fp = pcbnew.FootprintLoad(fp_lib_path(lib), name)
        fp.SetFPID(pcbnew.LIB_ID(lib, name))
        fp.SetReference(e["ref"])
        fp.SetValue(e.get("value", e.get("label", e["ref"])))
        fp.SetAttributes(fp.GetAttributes() | pcbnew.FP_BOARD_ONLY | pcbnew.FP_EXCLUDE_FROM_BOM
                         | pcbnew.FP_EXCLUDE_FROM_POS_FILES)
        board.Add(fp)
        x, y, rot = e["at"]
        fp.SetPosition(mm(x, y))
        fp.SetOrientationDegrees(rot)
        for pad in fp.Pads():
            n = e.get("nets", {}).get(pad.GetNumber())
            if n:
                if n not in netinfo:
                    raise SystemExit(f"EXTRA {e['ref']}: 网络 {n} 不存在（可用: {', '.join(sorted(netinfo)[:20])}...）")
                pad.SetNet(netinfo[n])
        if e.get("label"):
            add_text(board, e["label"], x, y - 1.8, h=0.7)

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

    # 天线区：模组上沿一条两层禁走线/过孔/铺铜，比模组两侧各宽 3mm（封装自带的禁布区只覆盖模组宽度）
    ax0, ax1 = ux - 6.84 - 3.0, ux + 6.84 + 3.0     # 模组宽度两侧各多 3mm
    add_rule_area(board, "antenna_keepout", [(ax0, 0), (ax1, 0), (ax1, 5.7), (ax0, 5.7)],
                  layers=(pcbnew.F_Cu, pcbnew.B_Cu), tracks=True, vias=True, pour=True)
    # Type-C 外壳下方禁过孔（外壳接 SHIELD，不是 GND）
    jx, jy, _ = PLACE["J1"]
    add_rule_area(board, "usbc_shell_novia", [(jx - 3.0, jy - 4.5), (W, jy - 4.5),
                                              (W, jy + 4.5), (jx - 3.0, jy + 4.5)],
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
    # 顶面：按键（标在按键下方）、RGB、电源输出焊盘
    for ref, name in (("SW1", "RST"), ("SW2", "BOOT")):
        add_text(board, name, PLACE[ref][0], PLACE[ref][1] + 2.25, h=0.6)
    add_text(board, "RGB", PLACE["D5"][0], PLACE["D5"][1] + 1.75, h=0.6)
    j5x, j5y, _ = PLACE["J5"]
    for k, name in enumerate(["3V3", "GND", "5V"]):
        add_text(board, name, j5x + 4.6 * k + 1.85, j5y, h=0.7, angle=90)
    # 背面：排针功能、输出说明、板名
    px, py, _ = PLACE["J4"]
    for k, name in enumerate(["3V3", "GND", "IO0", "IO1", "IO3", "IO4", "IO5", "IO6"]):
        add_text(board, name, px + 2.54 * k, py - 2.2, layer=pcbnew.B_SilkS, h=0.7, angle=90)
    add_text(board, "USB OUT 5V/2A", 6.5, 13.0, layer=pcbnew.B_SilkS, h=0.8)
    add_text(board, "J5 3V3 <=150mA", j5x + 4.6, j5y - 2.3, layer=pcbnew.B_SilkS, h=0.6)
    add_text(board, "ESP32-C3 SWITCH v1.4", PLACE["U1"][0], 11.0, layer=pcbnew.B_SilkS, h=1.0)


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
