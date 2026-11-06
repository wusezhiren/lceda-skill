#!/usr/bin/env python3
"""
嘉立创EDA专业版官方命令行（lceda-pro，客户端 ≥ 4.1.70 内置）的薄封装。

  python3 lceda.py doctor                       # 检查客户端/桥接是否就绪
  python3 lceda.py sessions                     # 列出编辑器会话
  python3 lceda.py run step.js [--args '{"k":1}'] [--timeout 300] [--session ID]
  python3 lceda.py run step.js --args-file input.json  # 大参数或含空格路径
  python3 lceda.py exec 'return await eda.dmt_Project.getCurrentProjectInfo()'
  python3 lceda.py run export.js --out jlcpcb/          # 返回值里的 fileOut(...) 写到 jlcpcb/
  python3 lceda.py run import.js --in project.zip       # 脚本里 fileIn("project.zip") 取回 File
  python3 lceda.py run scripts/pcb_dump.js --json dump.json  # 返回值整体写入 JSON 文件，只打印摘要

run/exec 会自动在脚本前拼上 lib.js（公共函数），脚本内容是 async 函数体：
可 await，用 return 返回（需可 JSON 序列化），参数在 ARGS（= __CLI__.args）。
返回值打印为 JSON；业务失败请在脚本里 throw，这样退出码非 0。

环境变量：
  LCEDA_BIN   lceda-pro 可执行文件（默认 ~/tools/lceda-pro/lceda-pro，其次 PATH）
  DISPLAY / XAUTHORITY  客户端是 Electron 程序，需要 X 显示；未设置时自动找桌面的 Xwayland
"""

import glob
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
LIB = os.path.join(HERE, "lib.js")


def lceda_bin():
    b = os.environ.get("LCEDA_BIN") or os.path.expanduser("~/tools/lceda-pro/lceda-pro")
    if os.path.exists(b):
        return b
    for name in ("lceda-pro", "easyeda-pro"):
        p = shutil.which(name)
        if p:
            return p
    sys.exit("找不到 lceda-pro，可设置 LCEDA_BIN 或先安装嘉立创EDA专业版客户端（≥4.1.70）")


def env():
    e = dict(os.environ)
    if not e.get("DISPLAY"):
        e["DISPLAY"] = ":0"
        auth = sorted(glob.glob(f"/run/user/{os.getuid()}/.mutter-Xwaylandauth.*"))
        if auth and not e.get("XAUTHORITY"):
            e["XAUTHORITY"] = auth[0]
    return e


def call(args, timeout=120):
    """运行 lceda-pro，返回解析后的 JSON 信封 {"ok":..., "value"/"error":...}。"""
    p = subprocess.run([lceda_bin(), *args], capture_output=True, text=True, env=env(),
                       timeout=timeout + 30)
    # stdout 里混有 Chromium 日志，取最后一个以 { 开头的 JSON 行
    for line in reversed(p.stdout.splitlines() + p.stderr.splitlines()):
        line = line.strip()
        if line.startswith("{") and '"ok"' in line:
            return json.loads(line)
    return {"ok": False, "error": {"code": "NO_JSON", "message": (p.stdout + p.stderr)[-2000:]}}


def pick_session(explicit=None):
    if explicit:
        return explicit
    r = call(["session", "list"], 30)
    if not r.get("ok"):
        sys.exit(f"session list 失败: {r.get('error')}")
    alive = [s for s in r["value"] if s.get("status") == "alive"]
    if not alive:
        sys.exit("没有打开的编辑器窗口：先启动客户端并登录（或 lceda-pro open）")
    # 优先用户打开的可见窗口
    alive.sort(key=lambda s: (s.get("headless", False), s.get("origin") != "user"))
    return alive[0]["sessionId"]


def run_code(code, args=None, timeout=120, session=None, infiles=()):
    sid = pick_session(session)
    import base64
    files = {os.path.basename(f): base64.b64encode(open(f, "rb").read()).decode() for f in infiles}
    src = (open(LIB, encoding="utf-8").read()
           + "\nconst ARGS = (typeof __CLI__ !== 'undefined' && __CLI__.args) || {};\n"
           + "const INFILES = " + json.dumps(files) + ";\n" + code)
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as f:
        f.write(src)
        path = f.name
    try:
        cmd = ["invoke", "--session", sid, "--timeout", str(timeout * 1000), "--code-file", path]
        if args is not None:
            cmd += ["--args", json.dumps(args, ensure_ascii=False)]
        return call(cmd, timeout)
    finally:
        os.unlink(path)


def save_files(v, out_dir):
    """把返回值里的 {__file__, b64} 写到 out_dir，替换成 {saved: 路径, size}。"""
    import base64
    if isinstance(v, dict) and "__file__" in v and "b64" in v:
        os.makedirs(out_dir, exist_ok=True)
        path = os.path.join(out_dir, v["__file__"])
        with open(path, "wb") as f:
            f.write(base64.b64decode(v["b64"]))
        return {"saved": os.path.abspath(path), "size": v.get("size")}
    if isinstance(v, dict):
        return {k: save_files(x, out_dir) for k, x in v.items()}
    if isinstance(v, list):
        return [save_files(x, out_dir) for x in v]
    return v


def main(argv):
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    cmd, rest = argv[0], argv[1:]
    opts = {"--args": None, "--args-file": None, "--timeout": "120", "--session": None, "--out": ".", "--json": None}
    infiles = []
    pos = []
    i = 0
    while i < len(rest):
        if rest[i] == "--in":
            infiles.append(rest[i + 1])
            i += 2
        elif rest[i] in opts:
            opts[rest[i]] = rest[i + 1]
            i += 2
        else:
            pos.append(rest[i])
            i += 1
    if cmd == "doctor":
        r = call(["doctor"], 30)
    elif cmd == "sessions":
        r = call(["session", "list"], 30)
    elif cmd in ("run", "exec"):
        code = "\n".join(open(f, encoding="utf-8").read() for f in pos) if cmd == "run" else pos[0]
        if opts["--args"] and opts["--args-file"]:
            sys.exit("--args 和 --args-file 不能同时使用")
        args = json.loads(opts["--args"]) if opts["--args"] else None
        if opts["--args-file"]:
            with open(opts["--args-file"], encoding="utf-8") as source:
                args = json.load(source)
        r = run_code(code, args, int(opts["--timeout"]), opts["--session"], infiles)
    else:
        print(__doc__)
        return 2
    if r.get("ok"):
        value = save_files(r.get("value"), opts["--out"])
        if opts["--json"]:
            # 大结果（几何导出、DRC 明细）直接落盘，对话里只看摘要；注意 --out 是目录，只接 fileOut 文件
            with open(opts["--json"], "w", encoding="utf-8") as f:
                json.dump(value, f, ensure_ascii=False)
            keys = list(value)[:12] if isinstance(value, dict) else f"list[{len(value)}]" if isinstance(value, list) else type(value).__name__
            print(json.dumps({"json": opts["--json"], "bytes": os.path.getsize(opts["--json"]), "keys": keys}, ensure_ascii=False))
            return 0
        print(json.dumps(value, ensure_ascii=False, indent=1))
        return 0
    print(json.dumps(r.get("error"), ensure_ascii=False, indent=1), file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
