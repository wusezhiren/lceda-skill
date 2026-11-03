"""
导出嘉立创（JLCPCB）下单文件到 jlcpcb/：
  gerber.zip         Gerber + 钻孔（上传到 PCB 订单）
  BOM_JLCPCB.csv     Comment, Designator, Footprint, LCSC Part #（SMT 物料，按 LCSC 字段筛）
  CPL_JLCPCB.csv     Designator, Mid X, Mid Y, Layer, Rotation（贴片坐标，只含 BOM 里的件）

运行：python3 export_jlc.py
旋转角度按 KiCad 原样导出，下单后务必在嘉立创贴片预览里逐个核对极性/方向。
"""
# 按项目修改：NAME（工程名，= .kicad_pcb / .kicad_sch 的文件名）


import csv
import os
import shutil
import subprocess
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
NAME = "c3_switch_board"
PCB = os.path.join(HERE, NAME + ".kicad_pcb")
SCH = os.path.join(HERE, NAME + ".kicad_sch")
OUT = os.path.join(HERE, "jlcpcb")
BUILD = os.path.join(HERE, "build")

LAYERS = "F.Cu,B.Cu,F.Paste,B.Paste,F.Silkscreen,B.Silkscreen,F.Mask,B.Mask,Edge.Cuts"


def run(*args):
    r = subprocess.run(["kicad-cli", *args], capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit(f"kicad-cli {' '.join(args)} 失败:\n{r.stdout}\n{r.stderr}")


def main():
    os.makedirs(OUT, exist_ok=True)
    os.makedirs(BUILD, exist_ok=True)

    # 1. Gerber + 钻孔
    gdir = os.path.join(BUILD, "gerber")
    shutil.rmtree(gdir, ignore_errors=True)
    os.makedirs(gdir)
    run("pcb", "export", "gerbers", "--layers", LAYERS, "--subtract-soldermask", "-o", gdir + "/", PCB)
    run("pcb", "export", "drill", "--format", "excellon", "--excellon-units", "mm",
        "--excellon-separate-th", "--generate-map", "--map-format", "gerberx2", "-o", gdir + "/", PCB)
    zpath = os.path.join(OUT, "gerber.zip")
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(os.listdir(gdir)):
            z.write(os.path.join(gdir, f), f)
    print("Gerber:", zpath, sorted(os.listdir(gdir)))

    # 2. BOM（从原理图，按 LCSC 字段；不贴的件没有 LCSC 字段，THT 件单独排除）
    raw = os.path.join(BUILD, "bom_raw.csv")
    run("sch", "export", "bom", "--fields", "Value,Reference,Footprint,LCSC,${QUANTITY},${DNP}",
        "--labels", "Comment,Designator,Footprint,LCSC Part #,Qty,DNP",
        "--group-by", "Value,Footprint,LCSC,${DNP}", "--ref-range-delimiter", "", "-o", raw, SCH)

    # 3. 坐标（只要贴片件）
    pos = os.path.join(BUILD, "pos.csv")
    run("pcb", "export", "pos", "--format", "csv", "--units", "mm", "--side", "front",
        "--smd-only", "--exclude-dnp", "-o", pos, PCB)
    with open(pos, encoding="utf-8") as f:
        pos_rows = {r["Ref"]: r for r in csv.DictReader(f)}

    bom_rows, smt_refs = [], set()
    with open(raw, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if not r["LCSC Part #"].strip() or r["DNP"].strip():
                continue
            refs = [x.strip() for x in r["Designator"].split(",")]
            refs = [x for x in refs if x in pos_rows]          # 去掉插件件（如 USB-A）
            if not refs:
                continue
            smt_refs.update(refs)
            r["Designator"] = ",".join(refs)
            r["Qty"] = str(len(refs))
            r["Footprint"] = r["Footprint"].split(":")[-1]
            bom_rows.append(r)
    with open(os.path.join(OUT, "BOM_JLCPCB.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["Comment", "Designator", "Footprint", "LCSC Part #", "Qty"],
                           extrasaction="ignore")
        w.writeheader()
        w.writerows(bom_rows)

    with open(os.path.join(OUT, "CPL_JLCPCB.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["Designator", "Mid X", "Mid Y", "Layer", "Rotation"])
        for ref in sorted(smt_refs, key=lambda s: (s.rstrip("0123456789"), int(s[len(s.rstrip("0123456789")):] or 0))):
            p = pos_rows[ref]
            w.writerow([ref, f'{float(p["PosX"]):.3f}mm', f'{float(p["PosY"]):.3f}mm',
                        "Top", f'{float(p["Rot"]):.0f}'])

    not_smt = sorted(set(pos_rows) - smt_refs)
    print(f"BOM: {len(bom_rows)} 种，{len(smt_refs)} 颗贴片；CPL: {len(smt_refs)} 行")
    if not_smt:
        print("有坐标但不在 BOM 里（不贴）:", not_smt)


if __name__ == "__main__":
    main()
