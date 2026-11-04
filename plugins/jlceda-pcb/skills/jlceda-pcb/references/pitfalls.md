# 嘉立创EDA 命令行踩坑清单

全部来自对客户端 4.1.93 的实测。客户端升级后 API 可能变化：遇到不符，用 `lceda-pro doc api --class-name X --method-name Y` 查当前版本。

## 环境与会话

- **用官方命令行，不要再装第三方桥接**：客户端 ≥4.1.70 自带 `lceda-pro`（国际版叫 `easyeda-pro`），`invoke` 能在编辑器里执行任意 JS。社区的 Run API Gateway / MCP 项目是旧方案。
- **Electron 程序需要 X 显示**：没有 `DISPLAY` 时会 core dump（“Missing X server”）。Wayland 桌面用 `DISPLAY=:0 XAUTHORITY=/run/user/$UID/.mutter-Xwaylandauth.*`。`lceda.py` 会自动处理。
- **首次启动停在注册页**（会话标题 `Regist`），这时 `invoke` 报 `BRIDGE_NOT_READY` 或一直挂起。需要用户在窗口里登录 → 下载激活文件 → 导入。激活后客户端会**自动重启一次**，会话 ID 会变——每次都重新 `session list`，别缓存 ID。
- 激活文件（如 `lceda-pro-activation.txt`）是账号凭据：**不要读取、不要拷进项目或仓库**。
- `invoke --code` 的代码上限 **1MB**（`CODE_TOO_LARGE`）。
- `invoke` 返回 `ok:true` 只表示代码跑完，不代表业务成功——业务条件不满足时在 JS 里 `throw`（lib.js 的 `must()`）。
- 本机 Wayland 下截不了屏（`X get_image failed`），看不到界面；需要知道界面状态时读 `top.document`（见下）或问用户。

## 器件与原理图

- **`lib_Device.getByLcscIds()` 在 4.1.93 返回空**；按立创编号精确查用 `searchByProperties({supplierId: 'C20917'})`。
- 查回来的器件**不带 libraryUuid**，要补上系统库 UUID（`lib_LibrariesList.getSystemLibraryUuid()`）才能 `create`。
- 器件的 `otherProperty['JLCPCB Part Class']` 直接告诉你是 `Basic Part` 还是 `Extended Part`——选料不用再查嘉立创接口。
- `createProject()` **自带 Board1（Schematic1 + PCB1）**，不要再 `createSchematic/createPcb/createBoard`，否则多出 Board2。
- 原理图里 `getAll()` 第一个“器件”是图框（`componentType = 'sheet'`），真器件是 `'part'`；按类型过滤：`getAll('part')`。
- 放器件后位号是 `Q?`，用 `modify(id, {designator: 'Q1'})` 设。
- 原理图坐标单位 10mil，**Y 轴向上**。引脚 `rotation`：0 朝右、90 朝上、180 朝左、270 朝下；`x,y` 是引脚外端点。
- **连线用“带网络名的短线”**：`sch_PrimitiveWire.create([x1,y1,x2,y2], 'NET')`，同名自动连通（等同网络标签），程序生成最省事。

- **两脚器件的符号引脚长度不统一**：大多数电阻电容引脚端点在 ±20（10mil 单位），但 C1555（22pF）等符号是 ±15，轻触开关 TS-1088 是 ±30。按固定偏移连线会得到斜线，`sch_PrimitiveWire.create` 直接抛 `create failed!`（不返回 undefined）。放置后读取实际引脚坐标连线；`sch_style.js` 的 `place()` 会把两脚器件的 1 脚平移到 ±20 设计位置。
- **电源/地符号要在导线之后创建**：先放 `createNetFlag` 再画到符号引脚上的导线，导线可能不并入该网络；`sch_style.js` 把符号延后到 `flushLabels()` 里统一创建。
- **同一连通线组多处带网络名会报 DRC 警告 ONENETNAME**（“GND、GND”）：内部导线不命名，只给标签短线或一段导线命名。
- **同一立创编号可能有多条系统库记录**：C15127 有 `AO3401A_P`（Manufacturer Part 为空，DRC 报 ATTRMATCHCODE）和 `AO3401A_C15127`；`deviceByLcsc()` 已改为优先取型号属性完整的记录。
- **网络端口默认不显示名称**：`createNetPort` 的 Name 属性 `valueVisible=false`，需要可见时改属性。导线带网络名时默认显示标签，内部导线要显式隐藏。
- **刚改完某页立即导出网表可能缺该页器件**：保存后等几秒再 `sch_Netlist.getNetlist()`，并核对器件总数。
- **原理图 DRC**：`sch_Drc.check(true, false, true)` 返回 `[{type, rule, primitives}]`。有意悬空的引脚（CHECKFLOATPIN）、只在 PCB 落焊盘的单节点网络（SHOWDANDLING）属于预期警告，需逐条说明；NETOBJECTONGRID 表示标签端点不在 5 单位网格。

## 工程

- `createProject(name, undefined, teamUuid)` 在离线模式下的工程根目录（`dmt_Team.getAllTeamsInfo()` 返回的本地路径）新建 `<name>/` 文件夹；**同名文件夹已存在（哪怕只放了需求文档）时静默失败返回 undefined**。先把文档临时移出、删空目录、建工程，再把文档放回。
- 没有删除工程的 API；要“删掉旧工程重画”，备份后删图页或由用户在客户端/文件夹里删除。
- 客户端关闭后 `lceda.py sessions` 为空：`DISPLAY=:0 XAUTHORITY=<Xwayland auth> ~/tools/lceda-pro/lceda-pro open` 打开空编辑器，再 `openProject`。

## 原理图 → PCB

- `pcb_Document.importChanges()` **会弹“确认导入信息”对话框**，返回 true 但 PCB 还是空的，直到有人点“应用修改”。
- 自动化：invoke 的代码运行在沙箱里，没有 `document`，但 **`top.document` 可访问主界面**。先发起 `importChanges()`（不 await），轮询 `top.document` 里可见按钮，点击文字为“应用修改”的按钮，再 await（lib.js 的 `importToPcb()`）。同法可处理其他确认框。

## PCB

- PCB 坐标单位 **mil**，Y 轴向上。lib.js 里用 `mm()` 换算。
- 层号：`EPCB_LayerId.TOP=1, BOTTOM=2, BOARD_OUTLINE=11, MULTI=12, TOP_SILKSCREEN=3`。
- 多边形：`eda.pcb_MathPolygon.createPolygon([x, y, 'L', x2, y2, ...])`；铺铜要 `createComplexPolygon([[...]])`。
- `pcb_Document.autoRouting()`（嘉立创自带布线器）返回 `{totalNetsCount, successNetsCount, failedNets}`；只有一个焊盘的网络会出现在 failedNets，属正常。
- 导入的工程带的是别的软件算好的铺铜填充，会压到禁布区 → `pour.rebuildCopperRegion()` 重铺。

## DRC

- `pcb_Drc.check(true, false, true)` 返回**多层嵌套分组**，直接 return 会刷出上百 KB；用 lib.js 的 `drcSummary()` 摊平计数。
- **导入工程的默认规则要求过孔孔径 ≥0.5mm**（嘉立创实际 0.3mm），导致每个过孔报 Via Size。改规则：`overwriteCurrentRuleConfiguration(cfg.config)`——**传 `config` 字段本身**，传整个对象返回 false。
- 规则里 `viaInnerdiameter*` 实际是**孔径**、`viaOuterdiameter*` 实际是**外径**（字段名与含义相反），以 DRC 报错文字为准。

## 文件进出

- `sys_FileSystem.saveFileToFileSystem / readFileFromFileSystem` 需要用户在设置里开“扩展和独立脚本的外部交互权限”，否则抛错。
- **绕过**：导出时在 JS 里把 File 转 base64 返回，Python 写盘；导入时把文件 base64 嵌进脚本传入、JS 里 `new File([...])`（lib.js 的 `fileOut()` / `fileIn()`，`lceda.py --out / --in`）。不需要任何权限。
- 导出的 BOM / 坐标文件是嘉立创原生格式：**UTF-16、制表符分隔**，直接上传即可；自己解析时注意编码。

## KiCad 导入

- `sys_FileManager.importProjectByProjectFile(file, 'KiCad', ...)` 支持 **KiCad 9** 工程（官方文档只写了 5.x，但新版能用）。
- **zip 里的文件必须在根目录**；套一层文件夹时接口静默返回 undefined。
- 3D 模型（STEP）会让 base64 超过 1MB 上限，打包时去掉（`make_kicad_zip.sh`）。
- KiCad 符号里的 `LCSC` 字段导入后只是自定义属性，下单要的是**供应商编号**：`modify(id, {supplier: 'LCSC', supplierId})`。没有编号的件（安装孔、焊盘、插件排针）设 `addIntoBom: false`。
- `kicad2jlceda.py` 每次新建工程；**同名工程已存在时导入静默失败**，改版用新名字（如 `_v1_4`），旧工程在客户端里手动删。
- 打开工程后板子是延迟加载的，立刻 `getAll` 可能拿不到 Board/PCB → lib.js 的 `firstBoard()` 轮询等待。
- 导入的板子仍用 **KiCad 的封装**，贴片坐标的旋转角不一定符合嘉立创库的约定——下单预览里要逐个核对方向。原生路线用嘉立创库封装，没有这个问题。

## 下单

- `pcb_ManufactureData.placePcbOrder(interactive, ignoreWarning)` / `placeSmtComponentsOrder(...)`：交互模式弹窗等用户确认；非交互模式检查通过后**在新标签页打开下单页**。会把设计数据上传到嘉立创——**调用前必须征得用户同意**；付款仍由用户在下单页完成。

## PCB 布局（2026-11-04 实测）
- `getPrimitivesBBox` 返回的器件框包含丝印/外形层，比焊盘包络大得多；判断摆件冲突用焊盘（`pcb_check.py`），否则不是误报就是漏报。
- 位号默认位置与字号不管密度，0201 板上会大面积重叠；布局完成后必须跑 `pcb_silk.js` 再 `pcb_check.py --silk`。
- `lib_Footprint.updateDocumentSource()`、`lib_Footprint.openInEditor()` 在 4.1.93 对工程库调用直接抛 `Error: [object Object]`（原样回写也失败）；`lib_Footprint.create('project', …)` 能建空封装、`search(name,'project')` 能查到，`getDocumentSource(uuid,'project')` 可读（真实 libraryUuid 读回空串）。
- 原理图 `createShortCircuitFlag` 会把两侧网络整体合并，不是 net-tie。
- 内置 `autoRouting()` 小板 4 层也可能 >10 分钟，CLI 调用超时后客户端继续跑，结束时走线被回滚；`startAutoRouting()` 可用 `getAutoJobStatus/cancelAutoJob` 观察和取消。主布线用 Freerouting。
- 换成小封装器件后原理图符号引脚间距/位置会变（SOT-666 ESD 脚距 10、SOT-523 MOS 的 S/D 在正上下），原有连线 `create failed!`；先读新符号引脚再改。
- Freerouting：不要从 DSN 里删 GND 网络来“跳过”它 —— GND 焊盘会变成无网络，所有地孔/地线都成预存违规（实测 333 处）并堵住通道；用 `-inc GND`（类名即网络名）忽略布线。`freeroute.py` 已这样做。
- 立创导出的 DSN 有时不包含规则区（天线禁布区），布线器会穿过天线区；`freeroute.py` 按规则区外框注入 `(keepout (rect signal …))`。DSN 坐标与 PCB 坐标同为 mil、同原点。
- 预布线的线段只是“穿过”焊盘中心时，Freerouting 判为未连接并报 unrouted；在焊盘中心断开成多段（项目 plan 脚本里做后处理）。
- `pcb_PrimitivePad.create` 矩形焊盘：枚举是 `EPCB_PrimitivePadShapeType.RECTANGLE`（不是 RECT，写错就是 undefined），形状数组 `[RECTANGLE, 宽, 高, 圆角]` 四项；错误信息只有“无法创建焊盘图元”。
- Freerouting `-inc` 忽略的网络（如 GND）仍会把“同网络过孔碰焊盘”计入 pre-existing violations（实测 229 条全是 GND↔GND），不是真问题；已被固定铜皮完全连通的网络（如由多块 Fill 拼成的天线 ANT_FEED）也要加进 `--skip-nets`，否则每块铜皮算一条 unrouted，且只要有 unrouted 就跳过优化阶段。
- `importAutoRouteSesFile` 会把 DSN 里已有的固定导线/过孔再创建一份（同坐标重复，DRC 报 Hole to Hole），`freeroute.py` 导回后按坐标去重。
- 封装里的非金属化定位孔（例如全贴片 USB-C 的塑料定位柱孔，在封装源码里是 layerId 12 的圆形 FILL，DRC 叫 Slot Region）不会进 DSN，布线器会穿过去；用 `freeroute.py --keepout x1,y1,x2,y2` 补禁布区，铜皮也要让开。
- 让 Freerouting 不在某层布线：DSN 里把该层 `(type signal)` 改 `power` 还不够（日志 “declared as a power layer but no plane is defined … treated as a signal layer”），必须再加 `(plane GND (polygon Inner1 0 <板框坐标>))`。`freeroute.py --plane-layers Inner1` 默认这样处理 L2。
- 立创导出的 DSN 里每个网络 class 的 `(clearance 4.02)` 比全局 `(rule (clear 6.03))` 小，Freerouting 按 class 值布线，导回后立创 DRC 按 6mil 报大量 Track to Via / Pad to Track；`freeroute.py` 默认把 class 间距统一成全局值。
- Freerouting 2.5.0 整板布线会把部分已布通网络整条漏写进 SES（UART_RX 单独布正常，整板时 SES 里没有、日志也不报未布通），表现为导回后芯片引脚大量 Connection Error。改用 1.9（`freeroute.py` 默认 `--engine 19`，需要 DISPLAY）。检查办法：拿 DSN 的引脚坐标逐个比对 SES 走线端点。
- 0.4mm 间距 QFN（焊盘 0.28mm，焊盘与走线间距规则 0.152mm）进脚线宽上限约 0.216mm；DSN 默认 10mil 线宽会让芯片引脚一根都进不去，`freeroute.py` 默认信号线 6mil。
