---
name: jlceda-pcb
description: 使用嘉立创EDA专业版官方CLI原生绘制、参考旧板重画及修改原理图和PCB，配置官方Freerouting插件或DSN/SES外部布线，核对网表、DRC并导出生产文件。适用于立创EDA画板、自动布线慢、原生重画和整理制板流程；优惠券资格需按具体活动另行确认。
---

# 嘉立创EDA 脚本化设计与下单

嘉立创EDA专业版桌面客户端（≥4.1.70）内置官方命令行 `lceda-pro`：`invoke` 在正在运行的编辑器里执行 JavaScript，等于能调用全部扩展 API（`eda.*`）。本 skill 把它封装成：

- `scripts/lceda.py`：找会话、拼接 `lib.js`、执行脚本、解析 JSON、文件进出（`--in` / `--out` 目录收 `fileOut` 文件；`--json 文件` 把整个返回值落盘只打印摘要）
- `scripts/sch_style.js`：分区式 EVB 原理图版式函数（`frame/QT/place/W/NL/PWR/GND/PORT/OPORT/NC`），拼在 lib.js 之后使用，见 `references/schematic-layout.md`“推荐版式”
- `scripts/lib.js`：实测可用的公共函数（放器件、连线、导入 PCB 自动确认、板框、摆件、铺铜、DRC 汇总、文件 base64 进出、过孔规则）
- `scripts/freeroute.py`：**默认自动布线**，DSN 导出 → Freerouting 无界面 → SES 导回一条命令
- `scripts/start_freerouting.sh`：启动仅监听本机的官方插件配套布线服务（官方插件界面布线用）
- `scripts/normalize_dsn_regions.py`：按明确区域清单修正DSN伪焊盘，不移除原生禁布规则
- `scripts/verify_native_netlist.py`：按器件引脚集合核对原生导出网表，发现缺脚、漏网或错网时返回非零
- `scripts/pcb_dump.js` + `scripts/pcb_check.py` + `scripts/pcb_render.py`：导出 PCB 几何 → 本地查焊盘间距/近板边/器件互压/丝印重叠 → 渲染 PNG 目视；摆件每改一轮都跑
- `scripts/pcb_silk.js`：位号统一字号、自动找不重叠位置，放不下的隐藏并列出
- `scripts/gnd_islands.py` + `scripts/gnd_route.py` + `scripts/apply_stitch.js`：铺铜后按实际填充算 GND 连通 → 列出真孤岛 → 缝合孔/网格寻路（避开异网络铜、可打孔换层）接回主地 → 下发、重铺、DRC 一条命令（`pcbgeo.py` 为共用几何模块，需 `pip install shapely`）
- `scripts/gnd_stitch.py`：单个地焊盘就近补"短线 + 地孔"（布线后、铺铜前也能用）
- `scripts/chamfer.py`：≤134° 走线拐角自动切 45° 并校核间距，结果同样用 `apply_stitch.js` 下发
- `scripts/jlc_search.py`：嘉立创元件查询（`@` 前缀只查基础库），不依赖客户端
- `scripts/kicad2jlceda.py`：已有 KiCad 工程 → 嘉立创EDA 工程 → 下单文件，一条命令（本机不需要装 KiCad）
- `scripts/examples/`：`native_demo.js`（原生全流程）、`import_kicad.js`（KiCad 导入）、`export.js`（导出生产文件）

**省 token**：优先用现成的一条命令脚本（`kicad2jlceda.py`）和 `lceda.py` 的 `--out` / `--json` 落盘，只看摘要；JS 里 `return` 精简结果（计数、前几条），不要把整个器件列表/DRC 树返回到对话里。

参考资料：`references/design-review.md`（方案自查）、`references/pcb-layout-workflow.md`（**PCB 布局流程：面积账 → 锚点 → 按焊盘坐标摆 → 查/看循环 → 固定几何 → 布线 → 丝印**）、`references/layout-rules.md`（摆件/天线/布线规则）、`references/ordering.md`（下单参数、免费券、下单助手）。遇到报错先查 `references/pitfalls.md`；API 细节以客户端自带文档为准：`lceda-pro doc api --class-name <类> --method-name <方法>`。

布局布线还须遵循 `references/layout-emc-principles.md`：机械约束先行、模块化布局、短回路去耦、连续参考地、关键网络优先、热设计与可维修性检查；经验数值不替代数据手册、实际层叠及板厂工艺。

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
| 新设计或按参考板重画 | **原生**：在嘉立创EDA里新建工程、放库器件、接线和导入PCB；参考板只用于提取网表、尺寸与布局约束 |
| 用户要求直接转换 KiCad 工程 | **导入**：转换已有工程；不要把格式导入说成原生重画 |

**优惠券不是技术验收项**：原生工程、官方扩展、DSN/SES往返都不能单独证明符合优惠券规则。按具体券的当前条款或客服答复确认，不承诺领券或抵扣成功。外部布线在规则未确认时仅作试验，不发起订单。

参考旧板重画、官方插件（方案2）及DSN/SES（方案3）的完整流程见 `references/native-freerouting.md`。先备份，再另建工程，不在唯一原件上清空布线。

动手前先给方案：框图、选型理由、GPIO 分配、尺寸估计、BOM 粗估，按 `references/design-review.md` 自查（供电预算、strapping 脚、高边/低边开关、续流），把真正影响设计的问题一次问清（负载/供电/接口），用 AskUserQuestion 给推荐项。

选料：`python3 scripts/jlc_search.py "AO3400A" "0201 10kΩ" C20917`。**封装默认从小**：阻容优先 0201（10μF 用 0402、22μF 用 0603），IC/MOS 优先 SOT-523/353/666 或 DFN，晶振 2016，保险丝 0603；**全贴片**：连接器选外壳脚也是贴片的款（如全贴片 USB-C），焊线/输出焊盘做表贴大焊盘不开孔；只有载流/散热/焊线等硬约束才用大封装并写明理由。同等条件下再优先基础库（无换料费）。

**采购可得性优先**：优先选用目标采购及贴装平台当前有库存、可采购且支持所需贴装工艺的器件。先查询实际料号、库存、封装和贴装可用性，再确定选型及放置器件；仅有 EDA 符号或封装不代表有货。满足电气、热设计及尺寸要求后，优先基础库，其次有货的扩展库。缺货、停产或仅有自建库记录的器件先查有货替代，替代时重新核对引脚、封装和关键规格；确需使用时明确记录采购或手焊安排。BOM 记录供应商编号、查询日期及库存/贴装状态，正式导出前复核。

**价格约束**：比较原选器件与平台有货候选时，以相同采购数量阶梯、币种、含税口径及报价日期计算价差，优先控制在 ±5% 内，通常不超过 ±10%。未定原型号时，以满足相同关键规格的可采购候选作为比价基准。不要仅为有货或基础库身份接受明显溢价；同时核算扩展料费用及整板 BOM 成本。超过 +10% 的候选先继续找替代，确需采用则列明基准价、候选价、价差及原因并请用户确认；降价超过 10% 不作为拒绝理由，但需复核规格和采购条件是否一致。无可靠报价时标记待核价，不声称满足价格约束。

## 2A. 原生路线

以 `scripts/examples/native_demo.js` 为模板写项目脚本（建议拆成 `sch.js` / `pcb.js` 分步跑，出错好定位）：

1. **工程**：`dmt_Project.createProject(name, name, team)` → `openProject`。新工程自带 Board1，直接用。
2. **选料**：`deviceByLcsc('C20917')` + `brief(d)` 查型号、封装、`jlcClass`（Basic/Extended）。优先基础库，理由写进汇报。
3. **原理图**：默认采用 `references/schematic-layout.md` 的“分区式 EVB 原理图”版式（左侧接口栏 + 2×2 分区 + 蓝色模块标题 + 标准电源/地符号），用 `scripts/sch_style.js` 每页一个脚本绘制；先写期望网表 `{"nets":{...}}`，画完用 `verify_native_netlist.py` 比对、`sch_Drc.check` 查警告，并导出 3000px PNG 逐页看图。默认使用 A4 页面，先放入全部已选元器件，按实际符号、引脚和文字所需空间估算各模块面积，在 A4 内分区排版和连线；实际空间不足时再增加图页或调整页面尺寸，无需在开始前确定最终页面大小。用红色非电气分区线（或红框）区分主控、电源、按键、驱动、LED 等功能模块，并添加清晰模块标题和关键说明；具体顺序及验收见 `references/schematic-layout.md`。`schPlace(lcsc, 位号, x, y, rot)` 返回引脚表；`schNet(pinOf(part,'G'), 'GATE')` 在引脚端点画带网络名的短线（同名即连通），但模块内部优先画易读的直接连接，模块之间使用明确网络标签。坐标单位 10mil，电源可用 `GND`/`+3V3`/`+5V`。
   原理图右下角的默认水印、标识及标题栏区域须留空，器件、连线、模块框和说明文字均不得覆盖；布局时先按实际模板划定保留区，导出预览再次核对。
   **可读性与增量修改**：同一模块内部优先使用实际连线，少用网络标签代替局部连接；跨模块及公共电源可用网络标签。器件符号、引脚、位号、型号及连线与红框保持间距，不与框线重叠。调整布局时优先局部移动受影响模块及其连线、标签和边框，保留其他模块和图元；例如右下角被水印遮挡时仅移出相关模块，不整体删除重画。只有确实需要整体重构时才先备份并说明理由。
   **按原理排件**：模块内部依实际电源流、信号流按“输入 → 保护/滤波 → 处理/驱动 → 输出”布局，电源在上、接地在下；电容按真实连接画为对地支路。通过局部移动、旋转和直接连线让读者顺着电路理解工作过程，不按位号或器件类型机械排列。
   **朝向与美观**：连线前先调整器件朝向，使输入输出顺着主通路；串联器件沿通路，上拉向电源，下拉与旁路支路向地。旋转或镜像后重新核对引脚号、坐标和极性。采用正交短连线、T 形分支、标准电源地符号及对齐排版，避开文字与无关引脚；细则见 `references/schematic-layout.md` 的“器件朝向、连线与视觉规范”。
   **首页与页头说明**：原理图最前面设置设计总览，包含版本及修订记录、功能介绍、页面目录与介绍、系统功能框图；每个电路图页顶部标明版本、页名及本页功能摘要。默认从 A4 开始，总览内容较多时独立为首页，避免压缩电路或覆盖标题栏；要求见 `references/schematic-layout.md` 的“首页总览与页面说明”。
4. **导入 PCB**：`importToPcb()`（自动点“应用修改”），检查返回 `{ok:true, clicked:'应用修改'}`，再 `pcb_PrimitiveComponent.getAll()` 核对数量和焊盘网络。
5. **板框与摆件**：**模块化布局优先**——先按原理图分区拆模块，每个模块参照对应芯片官网的参考设计/数据手册 Layout 指南单独排好并核对，再用 `pcbPlaceModules()` 把模块整体集中摆到板上（流程见 `references/pcb-layout-workflow.md`“模块化布局”）。先按同一文档算面积账（不够就先改选型/板框并告知用户，不硬摆），再 `boardOutline(w, h)`（mm）、`pcbPlace({位号:[x,y,rot,'TOP'], ...})`。外围件按 `pcb_dump.js` 读出的**真实焊盘坐标**相对摆放；每轮 `pcb_check.py` 报 0 项、`pcb_render.py` 看图后再继续。摆件规则见 `references/layout-rules.md`。
6. **布线（默认 Freerouting）**：射频、功率主干、地孔等关键几何先画好，然后
   **走线与接地顺序**：PCB 走线优先采用内夹角 135° 的钝角折线（走向改变 45°）或圆弧过渡，避免锐角回折和直角；分支及焊盘入口也需避免形成尖角，导入自动布线结果后逐项检查。执行顺序固定为：**先完成全部电源与信号网络的走线及连通核对 → 地焊盘就近补 GND 过孔与必要短连 → 在可用空白区域适当多放 GND 缝合过孔 → 最后创建并重建顶层、底层 GND 铺铜 → 完整 DRC 与回流检查**。普通 GND 过孔放在地焊盘附近的可用铜面，不直接压在器件引脚或贴片焊盘中心，通过短线就近连接后再由铺铜汇入地平面；只有明确用于 EPAD 灌锡、散热或封装推荐的孔才允许位于对应焊盘区域。自动布线默认跳过 GND，GND 优先通过就近过孔与铺铜连接，不用长地线逐一串联地端；确因铜面隔断或局部回流需要时才补必要地线。关键去耦、ESD 及功率回流的地孔位置应提前预留，不能被信号走线挤占；铺铜前只对非 GND 网络做连通核对，最终必须确认包括 GND 在内的所有网络连通，无孤岛或回流绕远。
   `python3 scripts/freeroute.py --out <工作目录>/fr --passes 20`（导出 DSN → 剔除 GND 等铺铜网络 → 规则区转 keepout → Freerouting 1.9 布线（默认 `--engine 19`，需 DISPLAY；2.5 有漏写 SES 的问题） → 导回 SES，一条命令；Java 25 / jar 路径见脚本头）。没有布通的连接先查摆件/通道，再局部改线或换参数重跑；内置 `autoRouting()` 只用于个别网络补线（小板也可能跑十几分钟且结果被回滚）。用户点名要官方插件时按 `references/native-freerouting.md` 方案2在界面操作，不把命令行 DSN/SES 往返说成插件。布线器完成、函数返回成功均不代表电气连通或 DRC 通过。
7. **铺铜**：顶层和底层的铺铜统一使用 **GND 网络**，通过 `pourGnd(w, h)` 创建；不得将整面或局部铺铜设为电源、信号或无网络。电源和功率主干使用明确归属网络的走线或必要的局部实心铜图元（Fill），并与 GND 铺铜保持规则间距。天线区等禁布区先画规则区再铺，重建后核对上下层每个铺铜对象的网络均为 GND。
   **接地过孔适当加密**：默认主动增加上下层 GND 缝合过孔，优先布在模组接地周围、去耦电容地端、稳压器与 USB ESD 地端、功率回流及板边可用区域；大电流跨层回流采用并联地孔，不依赖单个过孔。按回流路径和可用空间布置，不机械追求数量；避开模组天线净空、槽孔、板边及所有层的异网络铜皮，孔径与间距符合实际制板工艺。加孔后重建铺铜，核对每个地孔实际接入 GND，重新检查间距和连通性。
   **过孔尺寸与费用**：普通信号过孔和 GND 缝合过孔优先采用嘉立创在当前板层、板厚、工艺及订单条件下**不加价的最小成品孔径**，外径同时满足对应环宽、可靠性与 DRC 要求。选型前核对当前官方工艺／报价条件，不将固定孔径或“免费”资格视为永久规则。只有密集逃线等明确特殊需求才采用更小孔径，并记录工艺、费用及可靠性影响；大电流、散热或灌锡等需求可采用较大孔径与外径，结合电流、孔铜厚度、温升及压降确定并联孔数，不能仅凭孔大就认定载流足够。脚本、自动布线器及 DRC 的孔径／外径设置须保持一致。
   **空白区域补小地孔**：在上下层有 GND 铜面、空间允许的空白区域适当增加小尺寸 GND 缝合过孔，使两面地铜有效连接；尺寸遵循上述不加价最小孔径原则，孔径 0.3mm、外径 0.6mm 仅作为待核对工艺的示例，不是固定默认值。默认实心连接，不以盲目增加数量代替回流设计；避开天线净空、安装／槽孔、板边、所有层的异网络铜及手焊操作区域，保持孔到孔及铜间距，不让密集反焊盘割裂电源或参考地。补孔后重建铺铜，检查每个孔确实接入 GND、无孤岛及新增 DRC 问题。
7a. **GND 孤岛修复**（铺铜后 DRC 有 `Connection Error`/GND 时）：DRC 报的是孤岛间缺失飞线的**一个端点**，常落在主地一侧，不要按报点逐个补线。固定流程：
   ```bash
   python3 scripts/lceda.py run scripts/pcb_dump.js --timeout 300 --json w/dump.json
   python3 scripts/gnd_islands.py w/dump.json --png w/islands.png        # 真孤岛清单（与 DRC 一致时为 0）
   python3 scripts/gnd_route.py w/dump.json w/st.json --stitch 1.6 --no-route --keepout <天线净空>   # 先缝合孔并大块
   python3 scripts/lceda.py run scripts/apply_stitch.js --args-file w/st.json --timeout 600        # 下发+重铺+DRC
   # 重新 dump → gnd_route.py（不带 --stitch）逐岛寻路 → apply；无路径时 --width 0.2 --gap 0.16，再不行就挪挡路的信号线
   ```
   先查根因：整排横贯的底层电源/信号线会把地平面一切两半，优先改走线或在其两侧上方用顶层铜跨接打孔；模组 EPAD 子焊盘常被铺铜整圈让开，顶层子焊盘连井字形地线、底层 EP 通孔向外拉线接主地。修完 `chamfer.py` 倒角、`pcb_silk.js` 整理后再跑一轮 DRC。
7b. **丝印**：`pcb_silk.js` 整理位号，`pcb_check.py --silk` 无重叠；功能标注（极性、测试点、板名）单独放。
   **铺铜连接方式**：普通 GND 缝合过孔默认采用直接／实心连接（Direct／Solid），不使用十字热焊连接；核对实际铺铜结果，确保铜面连续接入。普通需手焊的器件接地焊盘默认保留热焊连接，兼顾可焊性；模组 EPAD 灌锡通孔结合焊接工艺单独设置，直接连接有利于接地与散热，但需考虑大铜面吸热，必要时预热或热风辅助。不得将过孔的实心连接设置不加区分地套用到全部手焊焊盘。修改连接方式后重建铺铜并重新检查间距与连通性。
8. **DRC**：`drcSummary()` 核对间距与连通性。目标为0；固定障碍、格式丢失约束等问题先定位，不反复无限重跑，不通过放宽规则制造通过。未通过时保存试验版并明确剩余问题，不导出正式生产包。
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

参数怎么选、免费券怎么领、下单助手怎么自动填，见 `references/ordering.md`；其中活动与工艺条件需要在下单时重新核实，不当作永久有效规则。

提醒用户：导入路线的板子在贴片预览里要逐个核对方向；插件件（USB-A、排针）不在 SMT 里。

## 交付汇报

中文、表格为主：路线、客户端版本、工程名、器件数/基础库占比、DRC 结果、导出文件路径、是否已发起下单，以及需要用户做的事（核对方向、确认下单、手焊件）。不罗列试错过程。
