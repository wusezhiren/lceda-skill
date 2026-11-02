---
name: pcb-jlc-pipeline
description: 从一句需求做到嘉立创可下单的 PCB 全流程：方案规划 → SKiDL 写原理图（KiCad 9）→ 嘉立创元件查询（优先基础库、填立创 C 编号）→ pcbnew 脚本摆件 → Freerouting 自动布线 + A* 迷宫补线 → GND 铺铜/过孔/孤岛修复 → DRC 清零 → 导出 Gerber/BOM/CPL。用户提到“设计/画一块 PCB 板”“画原理图”“布板/布线”“嘉立创/立创贴片/JLCPCB SMT”“查立创编号/基础库”“出 Gerber/坐标文件”、或要做 ESP32/单片机小板（Type-C 供电烧录、MOS 开关 LED/电机、低功耗）时，都应使用本 skill，即使用户没说 KiCad 或 SKiDL。
---

# PCB 设计到嘉立创下单

一条把“我想要一块 X 功能的小板”变成**DRC 零错误、可直接上传嘉立创 SMT 下单**的文件的流水线。全部用脚本驱动（SKiDL + pcbnew Python + kicad-cli + Freerouting），可以反复重跑：改摆件或原理图后整条链重新生成，不在 GUI 里手改。

工具位置（本机）：SKiDL venv `~/tools/cadvenv/bin/python`；KiCad 9（系统 `python3` 可 `import pcbnew`，`kicad-cli`）；Java/Freerouting/乐鑫库由 `scripts/setup_tools.sh` 装到 `~/tools`。

遇到报错或怪现象，先查 `references/pitfalls.md`（每条都实际踩过）。

## 流程总览

| 阶段 | 产出 | 工具 |
|---|---|---|
| 1 需求与方案 | 框图、关键选型、待确认问题 | `references/design-review.md` |
| 2 原理图 | `<name>.py` → `.kicad_sch`/`.net`/PDF，ERC 0 错 | SKiDL（参考 `references/skidl_example.py`） |
| 3 选料 | 每颗料的立创 C 编号写进 `LCSC` 字段，`BOM.csv` | `scripts/jlc_search.py` |
| 4 摆件 | `.kicad_pcb`（无走线），外框不重叠 | `scripts/build_pcb.py` |
| 5 布线 | 走线 + GND 铺铜，DRC 0 错 0 未连接 | `scripts/route_pcb.py` + `maze.py` |
| 6 导出 | `jlcpcb/gerber.zip`、`BOM_JLCPCB.csv`、`CPL_JLCPCB.csv` | `scripts/export_jlc.py` |

每个阶段结束都给用户一个简短汇报 + 需要他决定的事，再进入下一阶段。用户经常中途改需求（换接口、加/删功能），流水线可重跑，所以改起来不贵——但**改需求前先说清楚影响**（例如“2A 灯条 → 1.25mm 端子不够、保险丝要换、USB 5V 3A 是上限”）。

## 1. 需求与方案

先给方案再动手：框图（ASCII）、主控/电源/开关/接口选型及理由、GPIO 分配表、尺寸估计、BOM 粗估。用 `references/design-review.md` 自查，尤其是：
- 供电预算（USB 5V 上限 3A）、LDO vs DC-DC、保险丝内阻发热
- MCU strapping 脚、**复位后带内部上拉的 GPIO 不能驱动 MOS 栅极**
- 低边/高边开关的选择（输出是 USB-A 等外壳可能接地的口 → 高边）
- 感性负载续流

把真正影响设计的问题一次性问清（负载类型/电流、供电方式、接口形式、要不要电池），用 AskUserQuestion，给推荐项。不要问能自己查到或有惯例默认值的事。

## 2. 原理图（SKiDL）

在项目目录建 `<name>.py`，结构照 `references/skidl_example.py`：
1. 网络定义 → 各功能块（Type-C/保护/LDO/MCU/开关/扩展口）→ PWR_FLAG → `LCSC` 字典 → 模组 NC 脚
2. 运行：`~/tools/cadvenv/bin/python <name>.py`，生成 `.net`、`.kicad_sch`（`mode="labels"`，几秒出图）
3. 检查：`kicad-cli sch erc`（只剩 `lib_symbol_mismatch` 才算过）、`kicad-cli sch export pdf` 给用户看
4. 打印网表逐条核对关键网络（USB、电源、每路开关）——这一步抓到过接反的 LED。

库：KiCad 9 自带库缺的模组（如 ESP32-C3-MINI-1）从乐鑫库拷进项目 `lib/`，用 `scripts/downgrade_kicad_lib.py` 降格式，建项目 `sym-lib-table`/`fp-lib-table`（`${KIPRJMOD}/lib/...`），并放一个 `.kicad_pro`（没有工程文件时项目库表不生效）。

## 3. 选料（嘉立创）

```bash
python3 scripts/jlc_search.py "AO3400A" "@0402 10kΩ" "@Tactile" C20917
```
`@` 前缀只查基础库。策略：
- **能换基础库就换**（基础库无换料费）：比如 B5819WS→1N5819WS、0402 LED→0603 KT-0603R、钽电容→1206 陶瓷。说明每处替换的理由。
- 只能扩展库的（模组、Type-C、USB ESD、保险丝、LDO）挑库存大、原厂或口碑好的。
- 把 C 编号写进 SKiDL 的 `LCSC` 字典，重新生成；导出 BOM 核对（`kicad-cli sch export bom`）。
- 维护一份带“用途/备注/价格”的 `BOM.csv` 给人看。

## 4. 摆件（build_pcb.py）

把 `scripts/build_pcb.py` 拷到项目目录，改文件头标注的“按项目修改的部分”（板尺寸、`PLACE`、禁布区、丝印标注、网络类别）。

```bash
kicad-cli sch export netlist -o build/sch.net <name>.kicad_sch   # 必须用 KiCad 导出的网表
python3 build_pcb.py
kicad-cli pcb drc -o build/drc.rpt <name>.kicad_pcb               # 看 courtyards_overlap
kicad-cli pcb render --side top -w 900 -h 1300 -o build/top.png <name>.kicad_pcb
```

摆件是布线质量的决定因素，**按信号流排**：
- 先定大件：模组（天线贴板边）、连接器（开口朝板边）。量封装用 `pcbnew.FootprintLoad` 读 courtyard 和焊盘坐标。
- 电源主干一条路：输入 → 保险丝 → 主干 → LDO / 大电流开关 → 输出口；大电流件靠近各自的连接器。
- 每个功能块的小件挨着它服务的引脚，**引脚朝向对着去向**。
- 给模组引脚逃逸留通道（模组底边下方 ≥1.5mm）。
- 天线区整条两层禁铜；模组本体下禁顶层走线/过孔；Type-C 外壳下禁过孔。
- 全部元件放顶层（用户通常要求单面贴片）；排针定义、板名可放背面丝印。

## 5. 布线（route_pcb.py）

把 `scripts/route_pcb.py`、`scripts/maze.py` 拷到项目目录，改文件头标注的部分（`GND_LINKS`、`POWER_WIDEN`、`HIGH_CURRENT_THT`、Type-C 预布）。

```bash
export DISPLAY=:0 XAUTHORITY=$(ls /run/user/$(id -u)/.mutter-Xwaylandauth.* | head -1)   # 或用 xvfb-run
python3 route_pcb.py best 30 40 60 90      # 多种遍数各跑一次，保留未连接+违规最少的
kicad-cli pcb drc --schematic-parity --severity-error -o build/drc_err.rpt <name>.kicad_pcb
```

`route_pcb.py` 的流水线（每步都为了解决一个实际问题）：
1. 清旧走线和铺铜（**保留规则区**）
2. 预布并锁定：Type-C D+/D- 交叉、去耦电容地线（迷宫布线，此时板子空、必通）
3. 导出 DSN → Freerouting（`-inc GND`，GND 走铺铜不走线）→ 导回 SES
4. 用 DRC JSON 找未连接，`maze.py`（0.1mm 网格 A*，双层 + 过孔，先 0.28 再 0.22 间距）补线
5. 电源线有空间就加宽（`POWER_WIDEN`）
6. 每个贴片 GND 焊盘就近打孔 → 两面铺 GND（贴片全连接、手焊通孔花焊盘、大电流通孔全连接）→ 网格缝合过孔 → 孤岛补孔（放不下就迷宫连到最近的 GND）

**如果还有未连接**：不要死磕 Freerouting 参数，看是哪根线、在哪，基本都是摆件把路堵死了——调摆件（挪开、旋转让引脚朝向去向、拓宽通道）后整条链重跑。用 `kicad-cli pcb export pdf --layers F.Cu,B.Cu,Edge.Cuts,F.Fab` + `pdftoppm` 出不带铺铜的走线图（先存一份删掉铺铜的副本）放大看。

**目标**：错误级 DRC 0 违规、0 未连接、0 封装错误，`--schematic-parity` 通过。剩余 silk 警告（连接器伸出板边、轻微重叠）可接受，嘉立创会裁掉焊盘上的丝印。

最后目视：`kicad-cli pcb render` 顶面/底面图，检查丝印（立创编号字段别上丝印）、天线区、大电流路径。

## 6. 导出（export_jlc.py）

```bash
python3 export_jlc.py
```
生成 `jlcpcb/gerber.zip`（Gerber+钻孔）、`BOM_JLCPCB.csv`（只含有 LCSC 编号的贴片件）、`CPL_JLCPCB.csv`（与 BOM 一一对应）。提醒用户：
- 插件件（USB-A、排针等）不在 SMT 里，手焊或选插件服务
- **下单后在嘉立创贴片预览里逐个核对极性/方向**（二极管、SOT-23、LED、Type-C 常差 90°/180°）
- 扩展料种数 = 换料费次数

## 交付汇报

用中文、表格为主：做了什么、关键取舍（为什么）、DRC 结果、板尺寸、物料种数/基础库占比/单价、文件位置、用户还需要做的事（核对方向、手焊件）。不要罗列过程中的试错。
