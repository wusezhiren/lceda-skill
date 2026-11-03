#!/usr/bin/env python3
"""
一条命令跑完整条链，只打印摘要（省 token）。在项目目录里运行：

  python3 pipeline.py                 # 原理图 → 网表 → 摆件 → 布线 → DRC → 导出
  python3 pipeline.py --from build    # 跳过原理图（只改了摆件 / 丝印）
  python3 pipeline.py --from route    # 只重布线
  python3 pipeline.py --from check    # 只检查 + 诊断
  python3 pipeline.py --passes 30 60  # 指定 Freerouting 遍数组合（默认 30 40 60 90）
  python3 pipeline.py --render        # 额外渲染 build/top.png、build/bottom.png（需要看图时才加）

约定：项目目录里有 <name>.py（SKiDL 原理图）、build_pcb.py、route_pcb.py、maze.py、export_jlc.py，
     工程名 <name> 取 export_jlc.py 里的 NAME。所有详细日志写到 build/pipeline.log。
输出：每步一行 ✔/✘；失败时附诊断（未连接项、GND 孤岛、违规类型计数），然后退出码 1。
"""

import glob
import json
import os
import re
import subprocess
import sys
import time

HERE = os.getcwd()
BUILD = os.path.join(HERE, "build")
LOG = os.path.join(BUILD, "pipeline.log")
STEPS = ["sch", "build", "route", "check", "export"]


def name_from_export():
    s = open(os.path.join(HERE, "export_jlc.py"), encoding="utf-8").read()
    return re.search(r'^NAME\s*=\s*"([^"]+)"', s, re.M).group(1)


def env():
    e = dict(os.environ)
    e.setdefault("KICAD9_SYMBOL_DIR", "/usr/share/kicad/symbols")
    e.setdefault("KICAD9_FOOTPRINT_DIR", "/usr/share/kicad/footprints")
    if not e.get("DISPLAY"):                       # Freerouting 1.9 需要 X
        auth = sorted(glob.glob(f"/run/user/{os.getuid()}/.mutter-Xwaylandauth.*"))
        if auth:
            e["DISPLAY"], e["XAUTHORITY"] = ":0", auth[0]
    return e


def run(cmd, timeout=3600):
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(f"\n$ {' '.join(cmd)}\n")
        p = subprocess.run(cmd, stdout=f, stderr=subprocess.STDOUT, env=env(), timeout=timeout, cwd=HERE)
    return p.returncode


def tail_log(pattern, n=6):
    lines = [l.rstrip() for l in open(LOG, encoding="utf-8", errors="replace") if re.search(pattern, l)]
    return lines[-n:]


def drc_json(pcb, parity=True):
    out = os.path.join(BUILD, "drc.json")
    cmd = ["kicad-cli", "pcb", "drc", "--format", "json", "-o", out, pcb]
    if parity:
        cmd.insert(3, "--schematic-parity")
    run(cmd, 300)
    return json.load(open(out, encoding="utf-8"))


def diagnose(pcb, d):
    """失败时的简短诊断：未连接项、违规类型计数、GND 孤岛位置。"""
    lines = []
    errs = [v for v in d["violations"] if v["severity"] == "error"]
    kinds = {}
    for v in errs:
        kinds[v["type"]] = kinds.get(v["type"], 0) + 1
    if kinds:
        lines.append("  违规: " + ", ".join(f"{k}×{n}" for k, n in kinds.items()))
        for v in errs[:4]:
            lines.append("    " + " ↔ ".join(f"{i['description'][:50]}@({i['pos']['x']-100:.1f},{i['pos']['y']-100:.1f})"
                                           for i in v["items"][:2]))
    for u in d["unconnected_items"][:6]:
        lines.append("  未连接: " + " ↔ ".join(i["description"][:60] for i in u["items"][:2]))
    if any("填充区" in i["description"] or "Zone" in i["description"]
           for u in d["unconnected_items"] for i in u["items"]):
        code = r'''
import pcbnew, sys
b = pcbnew.LoadBoard(sys.argv[1]); g = b.FindNet("GND").GetNetCode()
vias = [t.GetPosition() for t in b.GetTracks() if t.GetClass() == "PCB_VIA" and t.GetNetCode() == g]
for z in b.Zones():
    if z.GetIsRuleArea(): continue
    L = z.GetLayer(); poly = z.GetFilledPolysList(L)
    for i in range(poly.OutlineCount()):
        ol = poly.Outline(i)
        if not any(ol.PointInside(v) for v in vias):
            bb = ol.BBox(); pads = [f"{fp.GetReference()}.{p.GetNumber()}" for fp in b.GetFootprints() for p in fp.Pads()
                                    if p.GetNetCode() == g and ol.PointInside(p.GetPosition())]
            print(f"  GND孤岛 {pcbnew.LayerName(L)} x{pcbnew.ToMM(bb.GetLeft())-100:.1f}-{pcbnew.ToMM(bb.GetRight())-100:.1f} y{pcbnew.ToMM(bb.GetTop())-100:.1f}-{pcbnew.ToMM(bb.GetBottom())-100:.1f} 焊盘{pads}")
'''
        p = subprocess.run(["python3", "-c", code, pcb], capture_output=True, text=True)
        lines += p.stdout.splitlines()[:6] or ["  GND 两层铺铜之间不连通（整群孤立），看 build/pipeline.log 里的“孤立群”"]
    return lines


def main(argv):
    sys.stdout.reconfigure(line_buffering=True)   # 管道/后台运行时也逐行输出
    start = "sch"
    passes = ["30", "40", "60", "90"]
    render = "--render" in argv
    if "--from" in argv:
        start = argv[argv.index("--from") + 1]
    if "--passes" in argv:
        i = argv.index("--passes") + 1
        passes = []
        while i < len(argv) and argv[i].isdigit():
            passes.append(argv[i])
            i += 1
    os.makedirs(BUILD, exist_ok=True)
    open(LOG, "w").close()
    name = name_from_export()
    pcb, sch = f"{name}.kicad_pcb", f"{name}.kicad_sch"
    todo = STEPS[STEPS.index(start):]
    t0 = time.time()

    if "sch" in todo:
        if os.path.exists(sch):
            os.remove(sch)
        rc = run([os.path.expanduser("~/tools/cadvenv/bin/python"), f"{name}.py"], 900)
        errs = tail_log(r"errors found|Traceback|Error", 3)
        ok = rc == 0 and os.path.exists(sch) and not any("Traceback" in l for l in errs)
        if ok:
            run(["kicad-cli", "sch", "erc", "-o", os.path.join(BUILD, "erc.rpt"), sch], 300)
            erc = [l for l in open(os.path.join(BUILD, "erc.rpt"), encoding="utf-8")
                   if l.startswith("[") and "lib_symbol_mismatch" not in l]
            ok = not erc
            print(f"{'✔' if ok else '✘'} 原理图  ERC 问题 {len(erc)}" + ("".join("\n  " + l.strip()[:90] for l in erc[:5])))
        else:
            print("✘ 原理图生成失败:", *errs, sep="\n  ")
        if not ok:
            return 1
        run(["kicad-cli", "sch", "export", "pdf", "-o", f"{name}.pdf", sch], 300)
        run(["kicad-cli", "sch", "export", "netlist", "-o", os.path.join(BUILD, "sch.net"), sch], 300)

    if "build" in todo:
        if "sch" not in todo:
            run(["kicad-cli", "sch", "export", "netlist", "-o", os.path.join(BUILD, "sch.net"), sch], 300)
        rc = run(["python3", "build_pcb.py"], 600)
        miss = tail_log(r"未放置", 1)
        d = drc_json(pcb, parity=False)
        ov = [v for v in d["violations"] if v["type"] == "courtyards_overlap"]
        ok = rc == 0 and not miss and not ov
        print(f"{'✔' if ok else '✘'} 摆件  外框重叠 {len(ov)}" + (f"  {miss[0]}" if miss else "")
              + "".join(f"\n  {' ↔ '.join(i['description'][:30] for i in v['items'])}" for v in ov[:5]))
        if not ok:
            return 1

    if "route" in todo:
        rc = run(["python3", "route_pcb.py", "best", *passes], 3600)
        best = tail_log(r"选用遍数", 1)
        fixes = len(tail_log(r"迷宫补线|孤岛连线|已接回主地", 999))
        print(f"{'✔' if rc == 0 else '✘'} 布线  {best[0].strip() if best else '无结果'}  （迷宫/孤岛修补 {fixes} 处）")
        if rc != 0:
            print(*tail_log(r"Traceback|Error|失败", 4), sep="\n  ")
            return 1

    if "check" in todo or "route" in todo:
        d = drc_json(pcb)
        errs = [v for v in d["violations"] if v["severity"] == "error"]
        warns = len(d["violations"]) - len(errs)
        unc = len(d["unconnected_items"])
        parity = len(d.get("schematic_parity", []))
        ok = not errs and not unc and not parity
        print(f"{'✔' if ok else '✘'} DRC  错误 {len(errs)}  未连接 {unc}  原理图一致性 {parity}  （警告 {warns}，多为丝印）")
        if not ok:
            print("\n".join(diagnose(pcb, d)))
            return 1

    if "export" in todo:
        rc = run(["python3", "export_jlc.py"], 600)
        summ = tail_log(r"^BOM:", 1)
        print(f"{'✔' if rc == 0 else '✘'} 导出  jlcpcb/  {summ[0].strip() if summ else ''}")
        if rc != 0:
            return 1

    if render:
        for side in ("top", "bottom"):
            run(["kicad-cli", "pcb", "render", "--side", side, "-w", "900", "-h", "1200",
                 "-o", os.path.join(BUILD, f"{side}.png"), pcb], 300)
        print("  渲染: build/top.png build/bottom.png")
    print(f"完成 {time.time() - t0:.0f}s（详细日志 build/pipeline.log）")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
