---
name: jlceda-pcb
description: 从一句需求做到嘉立创下单的 PCB 全流程，全部在嘉立创EDA专业版里完成：方案规划 → 选料（立创 C 编号、优先基础库）→ 用客户端自带官方命令行 lceda-pro 以脚本画原理图和 PCB → 摆件/自动布线/铺铜 → DRC 清零 → 导出 Gerber/BOM/坐标 → 下单（含免费打样券规则、下单助手参数）。原生设计才能用 EDA 免费券；也能把已有 KiCad 工程导入。用户提到“设计/画一块 PCB 板”“画原理图”“布板”“改板/加焊盘/加模块”“立创EDA/嘉立创EDA/EasyEDA”“立创贴片/SMT 下单”“免费打样”“查立创编号”“lceda-pro”，或要做 ESP32/单片机小板时都应使用本 skill。
---

# 嘉立创EDA 脚本化设计与下单

嘉立创EDA专业版桌面客户端（≥4.1.70）内置官方命令行 `lceda-pro`：`invoke` 在正在运行的编辑器里执行 JavaScript，等于能调用全部扩展 API（`eda.*`）。本 skill 把它封装成：

- `scripts/lceda.py`：找会话、拼接 `lib.js`、执行脚本、解析 JSON、文件进出（`--in` / `--out`）
- `scripts/lib.js`：实测可用的公共函数（放器件、连线、导入 PCB 自动确认、板框、摆件、铺铜、DRC 汇总、文件 base64 进出、过孔规则）
- `scripts/jlc_search.py`：嘉立创元件查询（`@` 前缀只查基础库），不依赖客户端
- `scripts/kicad2jlceda.py`：已有 KiCad 工程 → 嘉立创EDA 工程 → 下单文件，一条命令（本机不需要装 KiCad）
- `scripts/examples/`：`native_demo.js`（原生全流程）、`import_kicad.js`（KiCad 导入）、`export.js`（导出生产文件）

**省 token**：优先用现成的一条命令脚本（`kicad2jlceda.py`）和 `lceda.py` 的 `--out` 落盘，只看摘要；JS 里 `return` 精简结果（计数、前几条），不要把整个器件列表/DRC 树返回到对话里。

参考资料：`references/design-review.md`（方案自查）、`references/layout-rules.md`（摆件/天线/布线规则）、`references/ordering.md`（下单参数、免费券、下单助手）。遇到报错先查 `references/pitfalls.md`；API 细节以客户端自带文档为准：`lceda-pro doc api --class-name <类> --method-name <方法>`。

## 0. 环境（每台电脑一次）

```bash
bash scripts/setup_lceda.sh          # 下载并解压客户端到 ~/tools/lceda-pro（免 sudo），启动并检查
python3 scripts/lceda.py doctor      # {"connected": true} 即桥接就绪
python3 scripts/lceda.py sessions    # 会话标题不能是 "Regist"
```
首次启动需要**用户**在客户端窗口里登录嘉立创账号、下载并导入激活文件（GUI 步骤，你做不了；激活文件是凭据，别碰）。激活后客户端会自己重启一次。

`lceda.py run x.js --args '{...}' --timeout 600`：脚本内容是 async 函数体，`ARGS` 取参数，`return` 返回结果，业务失败用 `must()`/`throw`（否则 `ok:true` 只代表代码跑完了）。

## 1. 选路线

| 情况 | 路线 |
|---|---|
| 新设计（默认） | **原生**：全程在嘉立创EDA里生成，封装/BOM/坐标都是嘉立创库数据，**能用 EDA 免费打样券** |
| 用户给了现成的 KiCad 工程 | **导入**：几分钟转成可下单状态；封装仍是 KiCad 的，**不能用 EDA 专用免费券** |

动手前先给方案：框图、选型理由、GPIO 分配、尺寸估计、BOM 粗估，按 `references/design-review.md` 自查（供电预算、strapping 脚、高边/低边开关、续流），把真正影响设计的问题一次问清（负载/供电/接口），用 AskUserQuestion 给推荐项。

选料：`python3 scripts/jlc_search.py "AO3400A" "@0402 10kΩ" C20917`，能换基础库就换（无换料费）。

## 2A. 原生路线

以 `scripts/examples/native_demo.js` 为模板写项目脚本（建议拆成 `sch.js` / `pcb.js` 分步跑，出错好定位）：

1. **工程**：`dmt_Project.createProject(name, name, team)` → `openProject`。新工程自带 Board1，直接用。
2. **选料**：`deviceByLcsc('C20917')` + `brief(d)` 查型号、封装、`jlcClass`（Basic/Extended）。优先基础库，理由写进汇报。
3. **原理图**：`schPlace(lcsc, 位号, x, y, rot)` 放器件，返回引脚表；`schNet(pinOf(part,'G'), 'GATE')` 在引脚端点画带网络名的短线（同名即连通）。按功能块分区放（坐标单位 10mil，块间距 300~500）。电源用网络名 `GND`/`+3V3`/`+5V` 即可。
4. **导入 PCB**：`importToPcb()`（自动点“应用修改”），检查返回 `{ok:true, clicked:'应用修改'}`，再 `pcb_PrimitiveComponent.getAll()` 核对数量和焊盘网络。
5. **板框与摆件**：`boardOutline(w, h)`（mm），`pcbPlace({位号:[x,y,rot,'TOP'], ...})`。摆件规则见 `references/layout-rules.md`：按信号流、大件先定、天线贴板边并加禁布带、连接器开口朝外、引脚朝去向、留逃逸通道。
6. **布线**：`eda.pcb_Document.autoRouting()`，看 `failedNets`（单焊盘网络失败正常）。失败多就调摆件重来；需要更强的布线器时可 `pcb_ManufactureData.getDsnFile()` 导出给 Freerouting，再 `pcb_Document.importAutoRouteSesFile()` 导回（未实测，按 doc 核对签名）。
7. **铺铜**：`pourGnd(w, h)` 两面 GND；天线区等禁布区先画规则区再铺。
8. **DRC**：`drcSummary()` 直到 `total: 0`。
9. **保存**：`eda.pcb_Document.save()`。

### 改板（原生工程）
| 改动 | 做法 |
|---|---|
| 加/删功能模块 | 原理图里 `schPlace`/`schNet` 加电路（或删器件、未用引脚不接）→ `importToPcb()` 同步 → 摆新件 → 局部自动布线 → 重铺铜 → DRC |
| 只加焊盘/测试点（接已有网络） | 只动 PCB：`eda.pcb_PrimitivePad.create(...)` 放焊盘并设网络（签名用 `lceda-pro doc api` 查），原理图不动；它不进 BOM |
| 挪件/改尺寸/改丝印 | 只动 PCB：`pcbPlace`、`boardOutline`，然后重布受影响的线、重铺铜、DRC |
| 换料（同封装） | 原理图里换器件或改 `supplierId`，同步到 PCB |
每次改完都 `drcSummary()` 到 0，再导出；改版下单用新文件名/版本号。

## 2B. 导入路线（KiCad → 嘉立创EDA，一条命令）

```bash
python3 scripts/kicad2jlceda.py <KiCad工程目录> <新工程名> [输出目录，默认 <工程目录>/jlceda]
```
一条命令完成：打包（文件放根目录、去 3D，base64 < 1MB）→ 导入成新工程 → `LCSC` 字段写成供应商编号（没编号的件移出 BOM）→ 过孔规则改成嘉立创工艺 → 重铺铜 → DRC → 导出 `gerber.zip/BOM.csv/CPL.csv`。只打印 3~4 行摘要：
```
✔ 打包 191367 字节（base64 约 249 KB，上限 ~1000 KB）
✔ 导入  器件 38  走线 352  过孔 104  立创编号 32  不进BOM 6  DRC 0
✔ 导出 gerber.zip(121706B)  BOM.csv(3618B)  CPL.csv(13216B)
```
完整返回存在 `<输出目录>/kicad2jlceda.json`，需要时再 grep。**同名工程已存在会导入失败**——KiCad 改版后用新名字（如 `xxx_v1_4`）。导入成功但后处理/导出中断时：`kicad2jlceda.py --fix-current [输出目录]` 只补跑后处理和导出。

导入后的修改直接在嘉立创EDA 工程里做（原生 API），不再回 KiCad。

## 3. 导出与下单

```bash
python3 scripts/lceda.py run scripts/examples/export.js --args '{"prefix":"my_board"}' --out <项目>/jlceda/
```
得到 `gerber.zip`、`BOM.csv`、`CPL.csv`（嘉立创原生格式，UTF-16 制表符分隔）。核对 BOM 里每颗贴片件都有 `Supplier Part`。

下单：`eda.pcb_ManufactureData.placePcbOrder(true)`（PCB）/ `placeSmtComponentsOrder(true)`（贴片），交互模式会在客户端弹出检查窗口，用户确认后打开下单页。**这一步会把设计数据上传到嘉立创，调用前先问用户**；付款、拼板、工艺选项由用户在下单页完成。也可以让用户手动上传导出的三个文件。

参数怎么选、免费券怎么领、下单助手怎么自动填，见 `references/ordering.md`。**用 EDA 专用免费券时整板必须原生设计、焊盘喷镀选无铅OSP**。

提醒用户：导入路线的板子在贴片预览里要逐个核对方向；插件件（USB-A、排针）不在 SMT 里。

## 交付汇报

中文、表格为主：路线、客户端版本、工程名、器件数/基础库占比、DRC 结果、导出文件路径、是否已发起下单，以及需要用户做的事（核对方向、确认下单、手焊件）。不罗列试错过程。
