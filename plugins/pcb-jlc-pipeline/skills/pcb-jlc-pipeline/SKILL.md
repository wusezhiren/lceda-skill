---
name: pcb-jlc-pipeline
description: 从一句需求做到嘉立创可下单的 PCB 全流程：方案规划 → SKiDL 写原理图（KiCad 9）→ 嘉立创元件查询（优先基础库、填立创 C 编号）→ pcbnew 脚本摆件 → Freerouting 自动布线 + A* 迷宫补线 → GND 铺铜/过孔/孤岛修复 → DRC 清零 → 导出 Gerber/BOM/CPL，一条命令 pipeline.py 跑完。用户提到“设计/画一块 PCB 板”“画原理图”“布板/布线”“改板/加焊盘/加模块/换布局/缩小尺寸”“嘉立创/立创贴片/JLCPCB SMT”“查立创编号/基础库”“出 Gerber/坐标文件”、或要做 ESP32/单片机小板（Type-C 供电烧录、MOS 开关 LED/电机、低功耗）时，都应使用本 skill，即使用户没说 KiCad 或 SKiDL。
---

# PCB 设计到嘉立创下单

把“我想要一块 X 功能的小板”变成**DRC 零错误、可直接上传嘉立创 SMT 下单**的文件。全部脚本驱动（SKiDL + pcbnew Python + kicad-cli + Freerouting），改需求后整条链重跑，不在 GUI 里手改。

工具（本机）：SKiDL venv `~/tools/cadvenv/bin/python`；KiCad 9（系统 `python3` 可 `import pcbnew`，`kicad-cli`）；Java/Freerouting/乐鑫库由 `scripts/setup_tools.sh` 装到 `~/tools`。报错或怪现象先查 `references/pitfalls.md`。

## 项目目录约定

```
<项目>/
  <name>.py          SKiDL 原理图（唯一的原理图源头）
  build_pcb.py       摆件：W/H、PLACE、EXTRA、禁布区、丝印、网络类别
  route_pcb.py       布线：GND_LINKS、POWER_WIDEN、HIGH_CURRENT_THT、Type-C 预布
  maze.py  export_jlc.py  pipeline.py      （照抄 scripts/，export_jlc.py 改 NAME）
  lib/ sym-lib-table fp-lib-table <name>.kicad_pro
  BOM.csv            给人看的物料表（用途/备注/价格）
  build/             中间文件和 pipeline.log    jlcpcb/  下单文件
```
新项目：把 `scripts/` 下的 `build_pcb.py route_pcb.py maze.py export_jlc.py pipeline.py` 拷进项目，改各文件头“按项目修改的部分”。

## 一条命令跑完（省 token 的主路径）

```bash
cd <项目> && python3 pipeline.py [--from sch|build|route|check|export] [--passes 30 60] [--render]
```
每步只打一行 ✔/✘，失败时附简短诊断（未连接两端、违规类型、GND 孤岛坐标和焊盘），详细日志在 `build/pipeline.log`。成功输出形如：
```
✔ 原理图  ERC 问题 0
✔ 摆件  外框重叠 0
✔ 布线  选用遍数 30：未连接 0，违规 0  （迷宫/孤岛修补 9 处）
✔ DRC  错误 0  未连接 0  原理图一致性 0  （警告 3，多为丝印）
✔ 导出  jlcpcb/  BOM: 23 种，31 颗贴片；CPL: 31 行
```
Freerouting 1.9 要 X 显示，pipeline 会自动找 Xwayland 的 `DISPLAY/XAUTHORITY`；整条约 2 分钟，用 `timeout` ≥ 600000 跑前台即可。

**省 token 规矩**：
- 只看 pipeline 的摘要行；不要 cat 整个 `pipeline.log`、`drc.json`、`.kicad_pcb`、网表。要细节时 `grep` 关键字。
- 用 `--from` 跳过没变的步骤（见下表）。
- 只有摆件变了、或摘要说失败且看不出原因时才 `--render` / 出走线图看；一次看一张，裁到板子范围。
- 量封装尺寸、焊盘坐标用一个小 pcbnew 脚本批量打印（courtyard bbox + 关键焊盘），不要逐个读封装文件。
- 失败时先读诊断行定位，再改对应的一处（摆件坐标、GND_LINKS 等），然后 `--from build` 或 `--from route` 重跑。

## 改需求：改哪个文件、从哪步重跑

| 改动 | 改哪里 | 重跑 |
|---|---|---|
| 加/删功能模块（新芯片、新一路开关、RGB 灯…） | `<name>.py` 加电路 + `LCSC` 字典；`build_pcb.py` 的 `PLACE` 给新位号坐标、`tidy_silkscreen` 加标注；大电流网络加进 `POWER_WIDEN`；`BOM.csv` 加行 | `--from sch`（默认） |
| **只加焊盘/测试点/焊线盘，接已有网络** | **只改 `build_pcb.py` 的 `EXTRA`**（原理图不动） | `--from build` |
| 挪件、旋转、改板尺寸、改丝印、改禁布区 | `build_pcb.py` | `--from build` |
| 布线结果不理想 / 改线宽 / 改去耦预布 | `route_pcb.py` | `--from route` |
| 只想复查 | — | `--from check` |
| 换料（同封装） | `<name>.py` 的 `LCSC` 字典 + `BOM.csv` | `--from sch` |

### 中途插入新模块的步骤
1. 先给用户方案：接哪个 GPIO（避开 strapping 脚、复位带上拉的脚）、供电从哪来、电流多大，选料（`jlc_search.py`，优先基础库）。
2. `<name>.py`：照现有功能块写成函数，新位号接着编；没用到的模组脚继续 `+= NC`；新料号写进 `LCSC`。
3. 封装：KiCad 自带库没有、或要和嘉立创库完全一致时，用 `~/tools/cadvenv/bin/easyeda2kicad --lcsc_id C52917434 --footprint --symbol --output lib/jlc` 按立创编号直接取，项目库表加 `jlc` 一项。
4. 核对引脚定义（数据手册或嘉立创库的 pin 名），尤其 LED/RGB/SOT-23 的脚序。
5. `build_pcb.py`：在 `PLACE` 给新位号坐标（挨着它服务的引脚、引脚朝向对着去向），加丝印标注。漏放的位号 pipeline 会报“未放置”。
6. `python3 pipeline.py`，看摘要；失败按诊断调摆件，`--from build` 重跑。
7. 更新 `BOM.csv`、丝印上的版本号；有嘉立创EDA 工程的话再跑一次 jlceda-pcb 的 `kicad2jlceda.py`。

删模块反过来：删电路、模组脚改 `+= NC`、删 `PLACE`/丝印/`POWER_WIDEN` 里的条目、删 `BOM.csv` 对应行。

### 只加焊盘（不动原理图）
```python
# build_pcb.py
EXTRA = [{"ref": "TP10", "footprint": "TestPoint:TestPoint_Pad_D1.5mm",
          "at": (5, 30, 0), "nets": {"1": "+5V"}, "label": "5V"}]
```
`nets` 写已有网络名（本地网络带 `/` 前缀如 `/VOUT1`，电源网络 `+5V`、`GND` 不带；写错会列出可用网络）。这些件标记为“仅板上”，原理图一致性检查跳过，也不进 BOM/坐标文件。焊线盘可用 `Connector_Wire:SolderWire-0.5sqmm_1x03_P4.6mm_D0.9mm_OD2.1mm` 之类。**需要进 BOM、或以后要在原理图里看到它**，就按“加模块”走。

## 各阶段要点

### 1 需求与方案
先给方案再动手：框图（ASCII）、选型及理由、GPIO 分配表、尺寸估计、BOM 粗估。用 `references/design-review.md` 自查：供电预算（USB 5V ≤3A）、LDO vs DC-DC、strapping 脚、复位带上拉的 GPIO 不能驱动 MOS 栅极、外壳可能接地的输出口用高边开关、感性负载续流。真正影响设计的问题一次问清（AskUserQuestion，给推荐项）；能查到或有惯例默认值的不问。改需求前先说清影响（例如“2A 灯条 → 保险丝要换、USB 3A 是上限”）。

### 2 原理图
结构照 `references/skidl_example.py`：网络 → 功能块 → PWR_FLAG → `LCSC` 字典 → 模组 NC 脚。`generate_schematic(mode="labels")`。KiCad 9 缺的模组从乐鑫库拷进 `lib/` 并用 `scripts/downgrade_kicad_lib.py` 降格式，建项目库表和 `.kicad_pro`。生成后打印关键网络逐条核对（抓到过接反的 LED）。

### 3 选料
```bash
python3 scripts/jlc_search.py "AO3400A" "@0402 10kΩ" C20917     # @ 前缀只查基础库
```
能换基础库就换（无换料费）；只能扩展库的（模组、Type-C、USB ESD、保险丝、小 LDO）挑库存大的。

### 4 摆件
按信号流排：先定模组（天线贴板边）和连接器（开口朝板边）→ 电源主干一条路 → 小件挨着它服务的引脚、引脚朝向对着去向 → 模组底边下方留 ≥1.5mm 逃逸通道。全部元件放顶层。禁布区：天线带（模组宽度两侧各 +3mm，两层全禁，安装孔可放在带的两侧）、模组本体下禁顶层走线/过孔、Type-C 外壳下禁过孔——`build_pcb.py` 按 U1/J1 坐标自动生成。
- 缩小尺寸：先算面积账（连接器纵深、模组、排针长度），再试布局。两个口放同一面正反叠放会让两根线同时插时打架，Type-C 外壳脚还是通孔，一般不可行；长条形“两端各一个口、天线朝长边”是常见解。
- 旋转连接器后，`route_pcb.py` 的 Type-C 预布会按封装朝向自动换算；自写的预布函数也要按 `GetOrientationDegrees()` 换算方向，不要写死“上/下”。

### 5 布线（route_pcb.py 内部顺序）
清旧走线和铺铜（保留规则区）→ 预布锁定（Type-C D+/D- 交叉、去耦电容地线）→ GND 走线套临时禁布区 → DSN → Freerouting（`-inc GND`）→ SES → DRC JSON 找未连接，`maze.py` 补线 → 电源加宽 → GND 焊盘打孔、两面铺铜、网格缝合、孤岛补孔/连群 → 重复过孔去重。`best` 模式跑多种遍数取最好。还有未连接基本是摆件堵路：看诊断坐标，挪件后 `--from build`。

### 6 导出
`jlcpcb/gerber.zip`、`BOM_JLCPCB.csv`、`CPL_JLCPCB.csv`。提醒用户：插件件（USB-A、排针）不在 SMT 里；下单后在嘉立创预览里逐个核对极性/方向（二极管、SOT-23、LED、Type-C 常差 90°/180°）；扩展料种数 = 换料费次数。要在嘉立创EDA 里打开/直接下单，用 jlceda-pcb skill 的 `kicad2jlceda.py`。

## 交付汇报
中文、表格为主：做了什么、关键取舍、DRC 结果、板尺寸、物料种数/基础库占比、文件位置、用户还要做的事。不罗列试错过程。
