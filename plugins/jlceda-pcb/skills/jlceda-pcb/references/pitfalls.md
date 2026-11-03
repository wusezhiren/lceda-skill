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
