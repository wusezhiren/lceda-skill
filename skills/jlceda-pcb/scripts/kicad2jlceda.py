#!/usr/bin/env python3
"""
一条命令：KiCad 工程 → 嘉立创EDA 新工程（立创编号写进供应商字段、过孔规则、重铺铜、DRC）→ 导出下单文件。
只打印摘要（省 token），详细返回写到 <out>/kicad2jlceda.json。

  python3 kicad2jlceda.py <KiCad工程目录> <新工程名> [输出目录，默认 <工程目录>/jlceda]
  python3 kicad2jlceda.py --fix-current [输出目录]     # 导入已成功、只补跑后处理 + 导出

前提：客户端已启动并登录（python3 lceda.py doctor 为 connected）。同名工程已存在会导入失败，换个名字。
"""

import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable


def lceda(*args, timeout=900):
    p = subprocess.run([PY, os.path.join(HERE, "lceda.py"), *args], capture_output=True, text=True,
                       timeout=timeout + 60)
    if p.returncode != 0:
        raise SystemExit(f"✘ {' '.join(args[:2])} 失败: {(p.stderr or p.stdout).strip()[-400:]}")
    return json.loads(p.stdout)


def main(argv):
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 2
    if argv[0] == "--fix-current":
        out = os.path.abspath(argv[1]) if len(argv) > 1 else os.path.abspath("jlceda")
        r = lceda("run", os.path.join(HERE, "examples/import_kicad.js"), "--timeout", "600")
    else:
        src, name = argv[0], argv[1]
        out = os.path.abspath(argv[2]) if len(argv) > 2 else os.path.join(os.path.abspath(src), "jlceda")
        zip_path = f"/tmp/{name}.zip"
        p = subprocess.run(["bash", os.path.join(HERE, "make_kicad_zip.sh"), src, zip_path],
                           capture_output=True, text=True)
        if p.returncode != 0:
            raise SystemExit(f"✘ 打包失败: {p.stderr.strip()[-300:]}")
        print("✔ 打包", p.stdout.strip().split("  ", 1)[-1])
        r = lceda("run", os.path.join(HERE, "examples/import_kicad.js"), "--in", zip_path,
                  "--args", json.dumps({"zip": os.path.basename(zip_path), "name": name}), "--timeout", "900")
    os.makedirs(out, exist_ok=True)
    json.dump(r, open(os.path.join(out, "kicad2jlceda.json"), "w"), ensure_ascii=False, indent=1)
    c, drc = r["counts"], r["drc"]
    ok = drc["total"] == 0
    print(f"{'✔' if ok else '✘'} 导入  器件 {c['comps']}  走线 {c['lines']}  过孔 {c['vias']}  "
          f"立创编号 {r['mapped']}  不进BOM {len(r['notInBom'])}  DRC {drc['total']}")
    for k, g in list(drc.get("groups", {}).items())[:5]:
        print(f"  {k} ×{g['count']} @{g['at'][:2]}")
    e = lceda("run", os.path.join(HERE, "examples/export.js"), "--args",
              json.dumps({"prefix": os.path.basename(out.rstrip('/')) or "board"}), "--out", out, "--timeout", "300")
    print("✔ 导出 " + "  ".join(f"{os.path.basename(v['saved'])}({v['size']}B)" for v in e.values()))
    print(f"  目录 {out}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
