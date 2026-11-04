#!/usr/bin/env python3
"""默认自动布线：嘉立创EDA 导出 DSN → Freerouting（无界面）→ 导回 SES。

用法：
  python3 scripts/freeroute.py --out work/fr [--passes 20] [--threads 6] [--skip-nets GND] [--keep-dsn-regions]

步骤：
  1. 保存 PCB，导出 board.dsn（已有导线/过孔/铜皮作为固定图元一起导出 —— 射频、功率等预布线先画好）
  2. --skip-nets 中的网络（默认 GND：靠铺铜 + 地孔连接）用 Freerouting 的 -inc 忽略：网络保留在 DSN 里，
     焊盘/地孔仍按 GND 识别，只是不布线。不要从 DSN 删网络 —— 删了以后 GND 焊盘变成无网络，地孔和短线全成“违规”并挡通道
  3. 原生规则区（禁布区）：4.1.93 有时导出成无网络伪焊盘（交给 normalize_dsn_regions.py 转 keepout），
     有时根本不导出；后一种情况按规则区外框注入 (keepout (rect signal …))，否则布线器会穿过天线区
  预布线（射频线等）要在每个焊盘中心断开成单独线段：线只是“穿过”焊盘时 Freerouting 认为没连上
  4. Freerouting 2.5（需 Java 25；FREEROUTING_JAVA / FREEROUTING_JAR 可覆盖默认路径）
  5. importAutoRouteSesFile 导回，打印导回前后导线/过孔数；之后照常重建铺铜 + 立创 DRC 验收
所有中间文件、Freerouting 日志都在 --out 目录。布线器“完成”不等于连通，必须看立创 DRC。
"""
import argparse, json, os, re, shutil, subprocess, sys, time
from pathlib import Path

HERE = Path(__file__).resolve().parent
LCEDA = [sys.executable, str(HERE / 'lceda.py')]
# 默认用 1.9：2.5.0 在整板布线时会把部分已布通的网络整条漏写进 SES（实测 UART_RX 单独布能出，整板布则 SES 里没有、也不报未布通），
# 且 2.5 有未布通就跳过优化。1.9 无 headless 模式，需要 DISPLAY（不弹窗口，但要能连 X）。
ENGINES = {
    '19': (str(Path.home() / 'tools/jre/bin/java'), str(Path.home() / 'tools/freerouting/fr19.jar')),
    '25': (str(Path.home() / 'tools/jre25/bin/java'), str(Path.home() / 'tools/freerouting/freerouting-2.5.0.jar')),
}


def lceda(code, out=None, infiles=(), timeout=300):
    with open(out_dir / '_step.js', 'w', encoding='utf-8') as f: f.write(code)
    cmd = LCEDA + ['run', str(out_dir / '_step.js'), '--timeout', str(timeout)]
    if out: cmd += ['--out', str(out)]
    for i in infiles: cmd += ['--in', str(i)]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 60)
    if r.returncode: sys.exit(f'lceda 执行失败：{r.stdout[-800:]}{r.stderr[-800:]}')
    try: return json.loads(r.stdout)
    except json.JSONDecodeError: return r.stdout


ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
ap.add_argument('--out', required=True); ap.add_argument('--passes', type=int, default=20)
ap.add_argument('--threads', type=int, default=max(1, (os.cpu_count() or 2) - 2))
ap.add_argument('--skip-nets', default='GND', help='逗号分隔；传空字符串则全部网络都布')
ap.add_argument('--keep-dsn-regions', action='store_true', help='不做规则区→keepout 转换')
ap.add_argument('--keepout', action='append', default=[], help='额外禁布矩形 x1,y1,x2,y2（mm，所有信号层），可多次给；用于 DSN 里缺失的封装定位孔等')
ap.add_argument('--plane-layers', default='Inner1', help='不走线的层（DSN 层名，逗号分隔），标成 power 平面；默认 Inner1 = L2 完整地平面（乐鑫等射频芯片指南要求）；传空字符串则所有层都可布线')
ap.add_argument('--plane-net', default='GND', help='平面层所属网络')
ap.add_argument('--clearance', type=float, default=None, help='网络类间距（mil）；默认取 DSN 全局 (rule (clear …)) 值。立创导出的 class 间距常比全局规则小（4.02 vs 6.03 mil），不统一的话布出来的线过不了立创 DRC')
ap.add_argument('--width', type=float, default=6, help='信号线宽（mil）。0.4mm 间距 QFN（焊盘 0.28mm、焊盘间距规则 0.152mm）进脚线宽不能超过约 8.5mil，默认 10mil 会导致芯片引脚全布不进去')
ap.add_argument('--net-width', default='+3V3:8,VBUS:12,+5V:12,OUT+:20', help='按网络单独指定线宽，NET:mil 逗号分隔')
ap.add_argument('--engine', default='19', choices=list(ENGINES), help='Freerouting 版本：19（默认）或 25')
ap.add_argument('--no-import', action='store_true', help='只布线不导回')
a = ap.parse_args()
out_dir = Path(a.out); out_dir.mkdir(parents=True, exist_ok=True)
JAVA, JAR = ENGINES[a.engine]
JAVA = os.environ.get('FREEROUTING_JAVA', JAVA); JAR = os.environ.get('FREEROUTING_JAR', JAR)
for p in (JAVA, JAR):
    if not Path(p).exists(): sys.exit(f'缺少 {p}：设置 FREEROUTING_JAVA / FREEROUTING_JAR（2.5 需要 Java 25，1.9 用 Java 17+）')

# 1. 导出 DSN + 规则区清单 + 现有统计
info = lceda('''await openPcb(); await eda.pcb_Document.save();
const regs = [];
for (const r of await eda.pcb_PrimitiveRegion.getAll()) {
	const id = r.getState_PrimitiveId(), bb = await eda.pcb_Primitive.getPrimitivesBBox([id]);
	regs.push({ id, layer: r.getState_Layer(), bbox: [bb.minX, bb.minY, bb.maxX, bb.maxY] });
}
const f = await fileOut(await eda.pcb_ManufactureData.getDsnFile('board'), 'board.dsn');
return { f, regs, lines: (await eda.pcb_PrimitiveLine.getAll()).length, vias: (await eda.pcb_PrimitiveVia.getAll()).length };''', out=out_dir)
dsn = out_dir / 'board.dsn'
print(f"导出 DSN：{dsn}（{dsn.stat().st_size} B），布线前导线 {info['lines']} 段、过孔 {info['vias']} 个，规则区 {len(info['regs'])} 个")

text = dsn.read_text(encoding='utf-8')
skip = [s for s in a.skip_nets.split(',') if s]
classes = set(re.findall(r'\(class\s+(\S+)', text))
miss = [n for n in skip if n not in classes]
if miss: print(f'警告：DSN 里没有网络类 {miss}，这些网络不会被忽略')

# 2. 规则区 → keepout
regs = info['regs'] if not a.keep_dsn_regions else []
in_dsn = [r for r in regs if r['id'] in text or r['id'].replace('e', '', 1) in text]
absent = [r for r in regs if r not in in_dsn]
for k in a.keepout:
    x0, y0, x1, y1 = (float(v) / 0.0254 for v in k.split(','))
    absent.append({'id': 'cli', 'bbox': [x0, y0, x1, y1]})
for ly in [x for x in a.plane_layers.split(',') if x]:
    text, k = re.subn(r'(\(layer ' + re.escape(ly) + r'\s*\(type )signal', r'\1power', text)
    # 只标 power 不够：没有 plane 定义时 Freerouting 仍当信号层用；按板框补一个覆盖整板的平面
    bnd = re.search(r'\(boundary\s*\(path signal [\d.]+ ([-\d. ]+)\)', text)
    if k and bnd:
        # 必须放在层定义之后（structure 段末尾），否则 Freerouting 报 layer name not found 并崩溃
        text, k = re.subn(r'\n  \)\s*\n(\s*)\(placement', lambda m: f"\n    (plane {a.plane_net} (polygon {ly} 0 {bnd.group(1).strip()}))\n  )\n{m.group(1)}(placement", text, count=1)
    print(f'{ly} 设为 {a.plane_net} 平面层（不布线）' if k and bnd else f'警告：{ly} 未能设为平面层')
g = re.search(r'\(rule\s*\(clear ([\d.]+)\)\)', text)
clr = a.clearance or (float(g.group(1)) if g else None)
if clr:
    text, k = re.subn(r'\(clearance [\d.]+\)', f'(clearance {clr})', text)
    print(f'网络类间距统一为 {clr} mil（{k} 处）')
# 立创导出 (class X 'X')：单引号 1.9 不认（DSN 没声明 string_quote），网络全落进默认类 → 线宽全变成默认 10mil。改双引号
text = re.sub(r"(\(class \S+ )'([^'\n]*)'", r'\1"\2"', text)
text = re.sub(r"(\(class\s+''\s*(?:.*\n)*?\s*\(width )[\d.]+", lambda m: m.group(1) + str(a.width), text, count=1)
nw = dict((k, float(v)) for k, v in (x.rsplit(':', 1) for x in a.net_width.split(',') if x))
text = re.sub(r'\(rule\s*\(width [\d.]+\)\)', f'(rule(width {a.width}))', text)
def _cw(m):
    return re.sub(r'\(width [\d.]+\)', f'(width {nw.get(m.group(1), a.width)})', m.group(0), count=1)
text = re.sub(r"\(class (\S+) '[^\n]*\n(?:.*\n)*?\s*\(width [\d.]+\)", _cw, text)
print(f'线宽：默认 {a.width} mil，单独指定 {nw}')
work = out_dir / 'work.dsn'; work.write_text(text, encoding='utf-8')
if in_dsn:
    man = out_dir / 'regions.json'; man.write_text(json.dumps({'regions': in_dsn}), encoding='utf-8')
    norm = out_dir / 'normalized.dsn'
    r = subprocess.run([sys.executable, str(HERE / 'normalize_dsn_regions.py'), str(work), str(norm), '--manifest', str(man)], capture_output=True, text=True)
    if r.returncode == 0: work = norm; print(f'{len(in_dsn)} 个规则区伪焊盘已转 keepout')
    else: print('警告：规则区转换失败：', (r.stdout + r.stderr).strip()[-300:])
if absent:
    t = work.read_text(encoding='utf-8')
    ko = ''.join(f"    (keepout (rect signal {x0:.2f} {y0:.2f} {x1:.2f} {y1:.2f}))\n" for x0, y0, x1, y1 in (r['bbox'] for r in absent))
    t = t.replace('  (structure\n', '  (structure\n' + ko, 1)
    work = out_dir / 'keepout.dsn'; work.write_text(t, encoding='utf-8')
    print(f'注入 {len(absent)} 个 keepout（未进 DSN 的规则区 + --keepout），禁止所有信号层走线/过孔')

# 4. Freerouting
ses = out_dir / 'board.ses'; log = out_dir / 'freerouting.log'
if ses.exists(): ses.unlink()
t0 = time.time()
cmd = [JAVA, '-Xmx4g', '-jar', JAR, '-de', str(work), '-do', str(ses), '-mp', str(a.passes)] + (['-inc', ','.join(skip)] if skip else [])
env = dict(os.environ)
if a.engine == '25':
    cmd += ['-mt', str(a.threads), '--gui.enabled=false', '--api_server.enabled=false']
else:
    env.setdefault('DISPLAY', ':0')
    if 'XAUTHORITY' not in env:
        xa = sorted(Path(f'/run/user/{os.getuid()}').glob('.mutter-Xwaylandauth.*'))
        if xa: env['XAUTHORITY'] = str(xa[0])
print('运行：', ' '.join(cmd))
with open(log, 'w') as lf:
    rc = subprocess.run(cmd, stdout=lf, stderr=subprocess.STDOUT, env=env).returncode
dt = time.time() - t0
tail = [l for l in log.read_text(errors='ignore').splitlines() if re.search(r'unrouted|incomplete|完成|finished|pass|ERROR|WARN', l, re.I)][-8:]
print(f'Freerouting 退出码 {rc}，耗时 {dt:.0f}s；日志要点：'); [print('  ', l[-200:]) for l in tail]
if not ses.exists(): sys.exit(f'没有生成 SES，见 {log}')

# 5. 导回
if a.no_import: sys.exit(0)
res = lceda('''await openPcb();
const ok = await eda.pcb_Document.importAutoRouteSesFile(fileIn('board.ses'));
await sleep(2000);
// SES 会把 DSN 里原有的固定导线/过孔再建一遍，按坐标去重
const seen = new Set(), kept = []; let dup = 0;
for (const v of await eda.pcb_PrimitiveVia.getAll()) {   // SES 重建的固定过孔尺寸可能不同、坐标差零点几 mil：同网络 0.2mm 内视为重复
	const n = v.getState_Net(), x = v.getState_X(), y = v.getState_Y();
	if (kept.some(k => k[0] === n && Math.hypot(k[1] - x, k[2] - y) < 0.2 * MM)) { await eda.pcb_PrimitiveVia.delete([v.getState_PrimitiveId()]); dup++; }
	else kept.push([n, x, y]);
}
for (const l of await eda.pcb_PrimitiveLine.getAll()) {
	const p = [[Math.round(l.getState_StartX()), Math.round(l.getState_StartY())], [Math.round(l.getState_EndX()), Math.round(l.getState_EndY())]].sort().join(';');
	const k = [l.getState_Net(), l.getState_Layer(), p].join('|');
	if (seen.has(k)) { await eda.pcb_PrimitiveLine.delete([l.getState_PrimitiveId()]); dup++; } else seen.add(k);
}
await eda.pcb_Document.save();
return { ok, dup, lines: (await eda.pcb_PrimitiveLine.getAll()).length, vias: (await eda.pcb_PrimitiveVia.getAll()).length };''', infiles=[ses], timeout=300)
print(f"导回 SES：{res}")
print('下一步：重建铺铜（rebuildPours / 自己的 pour 脚本）→ drcSummary() 分类核对连通与间距')
