---
name: jlceda-pcb
description: 用嘉立创EDA专业版（lceda-pro / easyeda-pro 桌面客户端自带的官方命令行）以脚本方式画原理图和 PCB、跑 DRC、导出 Gerber/BOM/坐标文件并在嘉立创直接下单。两条路线：原生（按立创 C 编号放器件，用嘉立创库封装，贴片方向无偏差）和导入（把已有 KiCad 工程导进嘉立创EDA再下单）。用户提到“立创EDA/嘉立创EDA/EasyEDA”“用立创的软件画板/下单”“导入嘉立创EDA”“立创贴片/SMT 下单”“lceda-pro”，或想让 PCB 设计直接对接嘉立创下单时都应使用本 skill；如果用户只要 KiCad 文件，用 pcb-jlc-pipeline。
---

# 嘉立创EDA 脚本化设计与下单

嘉立创EDA专业版桌面客户端（≥4.1.70）内置官方命令行 `lceda-pro`：`invoke` 在正在运行的编辑器里执行 JavaScript，等于能调用全部扩展 API（`eda.*`）。本 skill 把它封装成：

- `scripts/lceda.py`：找会话、拼接 `lib.js`、执行脚本、解析 JSON、文件进出（`--in` / `--out`）
- `scripts/lib.js`：实测可用的公共函数（放器件、连线、导入 PCB 自动确认、板框、摆件、铺铜、DRC 汇总、文件 base64 进出、过孔规则）
- `scripts/examples/`：`native_demo.js`（原生全流程）、`import_kicad.js`（KiCad 导入）、`export.js`（导出生产文件）

遇到报错先查 `references/pitfalls.md`；API 细节以客户端自带文档为准：`lceda-pro doc api --class-name <类> --method-name <方法>`。

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
| 新设计，目标是在嘉立创下单 | **原生**：全程在嘉立创EDA里生成，封装/BOM/坐标都是嘉立创库数据 |
| 已有 KiCad 工程（比如 pcb-jlc-pipeline 做的） | **导入**：几分钟导入并转成可下单状态；注意封装仍是 KiCad 的 |

电路方案本身（供电、GPIO、MOS 开关、保护、选料原则）与工具无关：先按 `pcb-jlc-pipeline` skill 的 `references/design-review.md` 过一遍，问清负载/供电/接口再动手。

## 2A. 原生路线

以 `scripts/examples/native_demo.js` 为模板写项目脚本（建议拆成 `sch.js` / `pcb.js` 分步跑，出错好定位）：

1. **工程**：`dmt_Project.createProject(name, name, team)` → `openProject`。新工程自带 Board1，直接用。
2. **选料**：`deviceByLcsc('C20917')` + `brief(d)` 查型号、封装、`jlcClass`（Basic/Extended）。优先基础库，理由写进汇报。
3. **原理图**：`schPlace(lcsc, 位号, x, y, rot)` 放器件，返回引脚表；`schNet(pinOf(part,'G'), 'GATE')` 在引脚端点画带网络名的短线（同名即连通）。按功能块分区放（坐标单位 10mil，块间距 300~500）。电源用网络名 `GND`/`+3V3`/`+5V` 即可。
4. **导入 PCB**：`importToPcb()`（自动点“应用修改”），检查返回 `{ok:true, clicked:'应用修改'}`，再 `pcb_PrimitiveComponent.getAll()` 核对数量和焊盘网络。
5. **板框与摆件**：`boardOutline(w, h)`（mm），`pcbPlace({位号:[x,y,rot,'TOP'], ...})`。摆件原则同 pcb-jlc-pipeline：按信号流、大件先定、天线贴板边、连接器开口朝外、引脚朝去向。
6. **布线**：`eda.pcb_Document.autoRouting()`，看 `failedNets`（单焊盘网络失败正常）。失败多就调摆件重来；需要更强的布线器时可 `pcb_ManufactureData.getDsnFile()` 导出给 Freerouting，再 `pcb_Document.importAutoRouteSesFile()` 导回（未实测，按 doc 核对签名）。
7. **铺铜**：`pourGnd(w, h)` 两面 GND；天线区等禁布区先画规则区再铺。
8. **DRC**：`drcSummary()` 直到 `total: 0`。
9. **保存**：`eda.pcb_Document.save()`。

## 2B. 导入路线（KiCad → 嘉立创EDA）

```bash
bash scripts/make_kicad_zip.sh <KiCad工程目录> /tmp/board.zip     # 文件在根目录、去 3D，base64 < 1MB
python3 scripts/lceda.py run scripts/examples/import_kicad.js --in /tmp/board.zip \
    --args '{"zip":"board.zip","name":"my_board"}' --timeout 900
```
脚本会：导入 → `LCSC` 字段写成供应商编号（没有编号的件移出 BOM）→ 过孔规则改成嘉立创工艺（0.3mm）→ 重铺铜 → DRC。检查返回的器件/走线/过孔数与 KiCad 一致、`drc.total` 为 0。

## 3. 导出与下单

```bash
python3 scripts/lceda.py run scripts/examples/export.js --args '{"prefix":"my_board"}' --out <项目>/jlceda/
```
得到 `gerber.zip`、`BOM.csv`、`CPL.csv`（嘉立创原生格式，UTF-16 制表符分隔）。核对 BOM 里每颗贴片件都有 `Supplier Part`。

下单：`eda.pcb_ManufactureData.placePcbOrder(true)`（PCB）/ `placeSmtComponentsOrder(true)`（贴片），交互模式会在客户端弹出检查窗口，用户确认后打开下单页。**这一步会把设计数据上传到嘉立创，调用前先问用户**；付款、拼板、工艺选项由用户在下单页完成。也可以让用户手动上传导出的三个文件。

提醒用户：导入路线的板子在贴片预览里要逐个核对方向；插件件（USB-A、排针）不在 SMT 里。

## 交付汇报

中文、表格为主：路线、客户端版本、工程名、器件数/基础库占比、DRC 结果、导出文件路径、是否已发起下单，以及需要用户做的事（核对方向、确认下单、手焊件）。不罗列试错过程。
