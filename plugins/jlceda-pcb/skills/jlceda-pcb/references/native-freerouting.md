# 原生重画与 Freerouting 布线

## 范围与交付

原理图、封装放置、板框、规则和最终检查在嘉立创EDA专业版内完成。Freerouting只承担布线，不把导入KiCad工程称为原生重画，也不保证优惠券资格。

交付新工程、原件备份、参考网表映射、阶段日志、原理图预览、PCB检查报告和流程说明。DRC未通过时输出到明确标记的试验目录，不作为可生产文件交付。没有用户明确要求，不提交订单、上传设计或支付。

## 1. 识别参考板

1. 查找目录指令、原理图、PCB、网表、BOM及旧脚本。记录哪个文件是实际参考版本，不默认旧计划中的勾选状态真实。
2. `lceda.py doctor` 和 `sessions` 确认客户端、会话和打开的工程；多窗口时显式传 `--session`。
3. 导出 `sys_FileManager.getProjectFile()`，并备份本地工程目录。不要读取或复制激活文件。
4. 参考板只提取尺寸、器件参数、网络及布局约束。用新名称创建原生工程，不清空唯一原件。
5. 对照库引脚而非只对照器件名。USB-C合并脚、LED极性、USB-A外壳焊盘常有编号差异。检查每个网络的 `(位号, 引脚号)` 集合；自动生成的网络名可以变，但节点集合必须一致。
6. 单独列出裸焊盘、测试点、安装孔、禁布区、走线电流、差分或阻抗要求。PCB-only测试点不能在原理图/BOM核对时静默丢失。

## 2. 原生原理图

- 使用 `dmt_Project.createProject()` 后打开自带Board和原理图页；等待页面可编辑。
- 分为“放器件”“按器件连接”“检查”三个阶段。每批保存并写成功检查点，失败批次先检查现场，禁止盲目重跑造成重复标签。
- 图页坐标单位10mil，PCB坐标单位mil。使用引脚真实坐标与朝向，不四舍五入、不假定所有符号朝向相同。
- `sch_PrimitiveWire.create(line, net)` 在4.1.93实测会自动创建网络属性。API的 `getState_Key()` 返回 `Name`，文档源码对应 `NET`，查询时兼容两者。再次 `createNetLabel` 会形成两个同名标签并触发 `ONENETNAME`；应修改已有属性，不重复添加。
- 已有重复标签时，4.1.93的属性 `delete()` 实测没有删除源码中的重复记录。先备份 `getDocumentSource()`，只对父对象确认为WIRE且值完全相同的重复NET记录做去重，再 `setDocumentSource()`、保存、复查DRC与网表；不同网络名不自动删除，不能全删ATTR记录。
- 图框属性不能全删。只清理确认需要清理的器件、导线或重复网络属性。
- 为明确不用的引脚设置 `noConnected`，而非为了让检查通过把它们接地。
- 导出PNG/SVG实际看图，检查密集引脚标签、框外对象、标题栏遮挡；运行原理图DRC，并与参考网表比对。`verify_native_netlist.py expected.json native.net` 的期望输入为 `{"nets":{"网络名":[["位号","引脚号"]]}}`，导出网表类型为 `EasyEDA`。只有自动生成网络名允许按完全相同的节点集合匹配。警告与错误分别报告，不把“没有异常抛出”写成验收通过。

## 3. 原生PCB

1. `importChanges()` 后需要点击“应用修改”；返回true不代表用户确认步骤已完成。
2. 验证器件数、位号集合和全部焊盘网络。不完整时暂停修复，不能直接开始布线。
3. 重画板框、放置器件及PCB-only焊盘，建立天线/模组/连接器禁布区。库封装原点不等于参考封装原点，应按已核对引脚的实际焊盘坐标匹配位置及旋转。
4. 布线前先检查间距。未布线连接错误是预期的，但短路、禁布区或机械干涉不是。
5. 工艺规则按目标板厂和工艺确认。电源主干与细引脚入口区分线宽，不能把整条VBUS粗线硬塞进ESD器件窄脚，也不能把整条电源任意缩细来换取布通。
6. 需要重建GND铺铜时在布线结果回灌后重建；是否在布线前保留铺铜以实测DSN和引擎支持情况为准。

## 4. 方案2：官方插件

2026-11-04本机准备环境：嘉立创EDA专业版4.1.93，EasyEDA官方扩展 `freerouting-intergration` 1.7.1（UUID `cb8695de3b6f4258a74f0c3b9aff73ea`），Freerouting2.5.0。

### 服务

Freerouting2.5.0的JAR要求Java25；Java21会报class版本69/65不兼容。不要覆盖已有Java21，另装兼容运行时或使用官方带运行时的发行包。下载版本及校验和从官方发布页确认。

```bash
FREEROUTING_JAVA=/path/to/java25/bin/java \
FREEROUTING_JAR=/path/to/freerouting-2.5.0.jar \
bash scripts/start_freerouting.sh
curl --fail http://127.0.0.1:37864/v1/system/status
```

脚本仅绑定127.0.0.1。为了兼容官方插件禁用服务认证，不对局域网或公网开放。默认端口37864与插件匹配，自定义端口时还须确认插件是否可配置。

### 安装与操作

1. 高级 → 扩展管理器，搜索FreeRouting安装；也可从官方发布页下载中文 `.eext` 后点“导入”。
2. 核对发布者与包来源，确认安全提示；在已安装项只给此扩展开启“外部交互”。不要全局放开所有扩展。
3. 打开目标PCB，导出布线前备份。插件会清理未锁定的导线、圆弧和过孔；需保留的关键走线/过孔先锁定。
4. 从FreeRouting菜单运行“直接自动布线”或“自定义自动布线”。先小轮数测试，再按结果调整；不要假定更多线程必然更快。
5. 记录开始/结束时间、迭代次数、引擎任务状态、导回是否成功，以及立创DRC的违规分类。
6. 检查DSN是否实际携带禁布区、线宽与间距。立创规则不一定全部映射到外部格式；如果缺失，不把插件输出直接用于生产。
7. 插件“完成”只说明服务任务和导入流程完成。重建铺铜、重新运行立创DRC并检查未连网络，才能评价布线质量。

### 自动化边界

CLI可用 `functions --session <ID>` 查看真实安装的扩展，再按 `invoke --help` 查调用方式。不要把独立脚本导出DSN、调用服务、导回SES包装成“已运行官方插件”。界面导入可在出现文件控件后使用标准File/DataTransfer操作，但不同客户端版本需重新检查DOM；不要写死未知内部接口或绕过权限。

## 5. 方案3：DSN/SES（脚本默认路线）

日常自动布线直接用 `python3 scripts/freeroute.py --out <dir>`，它按本节步骤自动完成导出、网络剔除、规则区转换、布线和导回，并把日志留在 `<dir>/freerouting.log`。以下为手动步骤与原理。

方案2不可用，或实测发现需要显式修正DSN约束时，保留方案2日志，然后明确报告切换，不静默替换。

```javascript
await openPcb();
return await fileOut(await eda.pcb_ManufactureData.getDsnFile('board'), 'board.dsn');
```

本地引擎的CLI参数按实际版本 `--help` 核对，勿把1.9版本参数照搬到2.5。导入前备份、核对层名和坐标变换，导入接口签名使用客户端文档查询：

```bash
lceda-pro doc api --class-name PCB_Document --method-name importAutoRouteSesFile
```

DSN若缺失规则，按其坐标、单位、层名和板框重新构造约束，再检查输出；不能把某块板的22mm板高、天线坐标或6.5mil间距硬编码成通用值。SES导回后实测检查线宽，立创可能按网络默认规则重设宽度。

### 实测兼容性：规则区变成伪焊盘

4.1.93在此板导出的DSN里，将三个规则区域写成 `image u1` 下不带网络的polygon padstack/pin，而非Specctra keepout。Freerouting因此报告25个初始违规，其中包括模组接地焊盘与规则区的碰撞；单纯增加迭代无法修复这些固定几何冲突。

`normalize_dsn_regions.py` 仅转换显式清单中的区域，不删除真实器件焊盘。清单来自原生 `pcb_PrimitiveRegion` ID和层号：

```json
{"regions":[{"id":"实际区域ID","layer":1}]}
```

```bash
python3 scripts/normalize_dsn_regions.py before.dsn normalized.dsn --manifest regions.json
"$FREEROUTING_JAVA" -Xmx4g -jar "$FREEROUTING_JAR" \
  -de normalized.dsn -do normalized.ses -mp 12 -mt 0 \
  --gui.enabled=false --api_server.enabled=false
```

脚本检查mil单位、零位移/零旋转正面合成image、唯一ID、层号、无网络及不共享的polygon padstack；不支持的格式直接失败。当前导出器还可能去掉ID中首个 `e`，脚本只对清单ID兼容这一变体。转换只影响外部DSN，原生规则区必须保留，回灌后核对其ID和几何。

Specctra普通keepout阻止走线和过孔，不阻止器件焊盘。它对原生“仅禁走线”规则可能更严格，故不能把转换称为全部约束等价。连接器槽孔、测试点间距及分类线宽还需单独核对。

默认保留原DSN间距；可选 `--clearance-mil` 只提高导出间距，不修改原生DRC。但全局提高间距也会影响细间距器件焊盘间距：本板统一8mil产生11个USB-C焊盘间初始违规，不能用这一参数替代分类工艺规则。

本板2026-11-04实测：方案2插件耗时约314秒，剩30个引擎未布通连接，回灌后立创DRC49项。转换伪焊盘并保留原DSN间距后，初始引擎违规为0，12轮约153秒，仍有29个引擎未布通连接；回灌后、铺铜前立创DRC42项。说明修正有效但并未完成可生产验收，不能把153秒与314秒当作等质量的加速比。

原生局部补线和铺铜后保留的较好版本为473段保存后的走线、38个过孔；立创DRC剩6项连通性错误，飞线3条，涉及GND、3V3、CTRL1。原理图和PCB的27网/131节点映射均通过检查，但这只证明网络归属正确，不证明物理连通；该版本仍按试验版归档，没有导出正式生产包。

补线优先限定失败网络并保留已有走线。4.1.93可用 `pcb_Document.startAutoRouting({RoutingNets:[...], existingPrimitiveMode:'keep'})` 获取jobId，再 `getAutoJobStatus()` / `getAutoJobLog()` 查询、`cancelAutoJob()` 取消；调用返回、job结束与DRC通过分别记录，避免后台任务未停就重试。GND铺铜默认移除孤岛（`preserveSilos:false`），不是关闭连通性检查。

增加过孔或改线后先重建铺铜，再检查间距；旧铺铜几何未避让新图元时会误报铜皮到过孔/孔的间距，不能据此直接修改DRC规则。模组大接地焊盘使用盘中过孔时，要记录孔径/焊盘直径并单独复核焊接工艺，DRC通过不等于已验证塞孔、焊锡流失或装配质量。

批量修改线宽前保存原生快照。本次4.1.93试验中逐线修改触发 `isAsync` 异常；部分修改已经落盘，仅恢复默认宽度未完整恢复原连接状态。不要将这种批处理称为验证成功。必要时从本工程的原生备份提取同UUID的PCB文档源码，通过 `setDocumentSource()` 整板回退，再重新铺铜和DRC；回退前仍保存当前现场，不操作其他工程。

## 6. 验收与记录

- 原理图网表与参考节点集合一致；NC与PCB-only例外逐项列出。
- 立创PCB DRC检查确实启用连通性，不能以布通率、函数返回true或日志“完成”代替。
- 区分未连接、间距、短路、板边/禁布、线宽/孔径、丝印问题。不能通过关闭规则或扩大容差伪造零错误。
- 测试点、孔、关键走线、天线区、连接器机械位置人工目视检查。
- 保存原生工程和布线前后文件，写明版本与当前验收状态。只有通过验收才导出正式生产文件；否则试验文件必须标记未通过。
- 优惠券资格另行确认，订单和付款不属于默认授权。

官方来源：
- https://github.com/easyeda/eext-freerouting-intergration
- https://github.com/freerouting/freerouting/releases
- https://prodocs.lceda.cn/cn/pcb/route-auto-routing/
