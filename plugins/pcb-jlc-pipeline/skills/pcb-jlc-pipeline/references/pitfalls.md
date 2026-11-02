# 踩坑清单

每一条都是实际踩过的。按阶段分组；遇到对应症状时先查这里。

## 目录
- [SKiDL / 原理图](#skidl--原理图)
- [KiCad 库与 kicad-cli](#kicad-库与-kicad-cli)
- [pcbnew Python API](#pcbnew-python-api)
- [Freerouting](#freerouting)
- [布局与布线](#布局与布线)
- [铺铜与过孔](#铺铜与过孔)
- [嘉立创](#嘉立创)
- [协作 / 文件](#协作--文件)

## SKiDL / 原理图

- **`from skidl import *` 会把 `skidl` 这个名字覆盖成子模块 `skidl.skidl`**。要改包级属性（如 `empty_footprint_handler`）必须用 `sys.modules["skidl"]`，否则改了不生效、PWR_FLAG 继续报“缺封装”。
- **函数里写 `gnd += x` 会让 `gnd` 变成局部变量** → `UnboundLocalError`。在函数里改成 `x += gnd`（把引脚加到网络上）。
- **`a & r & b` 串联按引脚 1→2 的顺序**。LED 符号是 1=K、2=A，直接串会接反；有极性的件显式写 `d["A"] += ...`。
- **继承符号（extends）的引脚和封装字段可能读不到**：AO3400A、USBLC6、TLV755xx 等用 `extends` 的符号，`footprint=` 要显式写，否则生成网表时报 “No footprint”。
- **`generate_schematic()` 默认的自动排版非常慢**（几分钟不出结果），用 `mode="labels"`（每个引脚挂网络标签），几秒出图。
- **KiCad ERC 报 `power_pin_not_driven`**：外部供电的网络（VBUS、+5V、GND、被 MOS 开关出来的输出）挂 `PWR_FLAG`。
- **ERC 剩下的 `lib_symbol_mismatch`** 是 schematizer 内嵌符号与库格式差异，无害。
- **原理图生成后，别在 KiCad GUI 里改原理图再保存**——下次 SKiDL 重生成会覆盖。目录里有 `~xxx.kicad_sch.lck` 说明 GUI 正开着，提醒用户“不保存关闭再重开”。

## KiCad 库与 kicad-cli

- **KiCad 9 自带库没有 ESP32-C3-MINI-1**，用乐鑫官方库；GitHub main 分支是 KiCad 10 格式，9 打不开 → `scripts/downgrade_kicad_lib.py`。
- 拷进项目的封装里 3D 路径是 `${KICAD8_3RD_PARTY}/...`，sed 成 `${KIPRJMOD}/lib/3d/...`。
- **项目库表的昵称要和符号里写的一致**：符号库叫 `Espressif`（schematizer 生成的 lib_id），封装库叫 `PCM_Espressif`（符号 Footprint 字段写的）。
- **项目库表只有在同目录存在 `.kicad_pro` 时才生效**；没有工程文件时 kicad-cli 报“当前配置不包含符号库”。
- **首次没开过 KiCad GUI 时 `~/.config/kicad/9.0/sym-lib-table` 不存在**，从 `/usr/share/kicad/template/` 拷一份。
- PCB 要用 **`kicad-cli sch export netlist`** 导出的网表建板：本地网络名带 `/` 前缀（`/EN`），这样 DRC 的原理图一致性检查（`--schematic-parity`）才不报 net_conflict；SKiDL 的 `.net` 名字不带前缀。
- 一致性检查要求封装 `SetPath(KIID_PATH("/" + 符号uuid))`；测试点/安装孔封装默认“从 BOM 排除”，要按符号属性同步，否则报 footprint_symbol_mismatch。
- 渲染：`kicad-cli pcb render`（3D PNG）；看走线用 `export pdf` + `pdftoppm`（系统没有 rsvg/inkscape/convert）。PDF 是 A4，坐标 = KiCad mm，按 `dpi/25.4` 裁剪。

## pcbnew Python API

- **`board.Save()` 会重写同名 `.kicad_pro`**：新建 `BOARD()` 保存后，工程里的网络类别会被清空成默认。网络类别/规则要在 **Save 之后**写回 `.kicad_pro`（`write_project_rules()`）。
- **SWIG 对象不能用 `is` 比较**：`fp is u1` 永远 False。比较位号或 uuid。
- KiCad 9 里规则区的铺铜开关叫 `SetDoNotAllowCopperPour`（不是 `...ZoneFills`）。
- 封装字段：`fp.SetField("LCSC", v)` 新建的字段**默认在丝印上可见**，要 `fp.GetFieldByName("LCSC").SetVisible(False)`，否则立创编号印满板子。
- 飞线对象（RN_NET）没导出到 Python；要找“未连接”，用 `kicad-cli pcb drc --format json`，里面有两端对象的 uuid，`board.GetItem(KIID(uuid))` 取回对象。
- JSON 坐标转回 `VECTOR2I` 有浮点误差，按 < 0.01mm 距离匹配焊盘，不要 `==`。

## Freerouting

- **2.x 的 jar 有 65MB**，GitHub 镜像常常只有 10~100KB/s；**1.9.0 只有 5MB**，命令行参数一样，但**必须有 X 显示**（启动就调 `getScreenSize`）。有桌面：`DISPLAY=:0 XAUTHORITY=/run/user/$UID/.mutter-Xwaylandauth.*`；没有：`xvfb-run`（要 sudo 装 xvfb）。会在用户桌面弹个窗口，跑完自动关。
- 命令：`java -jar fr19.jar -de x.dsn -do x.ses -mp <遍数> -inc GND -dct 0`。`-inc` 让它跳过某个网络类别。
- **被 `-inc` 跳过的网络，它的焊盘不再被当成障碍物**：EN 线会穿过模组底部接地焊盘的缝隙并打孔。所以模组本体下方必须加“禁走线 + 禁过孔”的规则区。
- **它会漏线**，而且每次结果不同。用 `route_pcb.py best` 多跑几种遍数，再用迷宫布线补齐。
- 宽线进不了细间距焊盘：0.8mm 电源线接不进 SOT-666（0.5mm 间距）的 VBUS 脚 → 换 SOT-23-6 封装，或给这段单独设窄线类别。

## 布局与布线

- **先按信号流排件，再布线**。乱摆交给自动布线，会得到电源走底层把地平面切碎、信号到处绕的结果。
- **USB-C 的 D+/D- 两面焊盘交错**（B7 D-、A6 D+、A7 D-、B6 D+）：自动布线常连不全。预布：D+ 在焊盘下方连 U 形，D- 在焊盘上方连 U 形（`preroute_usb_c()`）。
- Type-C 上方很窄：别在两组 VBUS 之间再放底层连线（挡住 D- 交叉）；CC 电阻、ESD 芯片、保险丝要按出线方向排。
- **模组底边引脚一排 0.8mm 间距，往下逃逸需要通道**：模组底边与下面元件之间至少留 1.5mm 给信号横向走。
- **元件引脚朝向要对着它的去向**（如 LED 阳极朝限流电阻），否则自己的另一个焊盘就挡路了。
- 天线：**板顶整条两层都禁铜**（模组封装自带的禁布区只覆盖模组宽度，两侧仍会铺地打孔）。
- Type-C 外壳接的是 SHIELD（1M//4.7nF 到地），外壳下方禁打 GND 过孔。

## 铺铜与过孔

- **清旧铺铜时只删非规则区**：`for z in board.Zones(): if not z.GetIsRuleArea(): remove`。之前全删把禁布区也删了，导致禁布区从未生效。
- GND 不交给自动布线：每个贴片 GND 焊盘就近打孔 + 两面铺铜 + 网格缝合过孔 + 孤岛补孔。
- **避让检查要包含所有钻孔（含 GND 通孔焊盘）**，否则过孔贴着排针的 GND 孔，报 hole_to_hole。
- 贴片焊盘与铺铜**全连接**（回流焊不需要花焊盘，避免 starved_thermal）；手焊的通孔用花焊盘，**但大电流通孔（如 USB-A GND）全连接**。
- **去耦电容的地先就近连到芯片 GND 脚并锁定**（布线前做），否则常被信号线围成孤岛。
- 模组底部中心接地焊盘阵列落在禁布区里，不能打孔（DRC items_not_allowed）；靠顶层铺铜连到四周 GND 脚即可。

## 嘉立创

- 元件查询用 jlcpcb.com 的 `selectSmtComponentList` 接口（`scripts/jlc_search.py`）；立创商城 `wmsc.lcsc.com` 返回 403。
- 基础库没有：ESP32 模组、Type-C、USBLC6、自恢复保险丝、小 LDO（只有 AMS1117/XC6206/HT7533，前者 Iq 5mA、后两者电流太小）——这些只能扩展库。
- 基础库**有**：0402/0603 常用阻容、AO3400A、AO3401A、1N5819WS、KT-0603R 红灯、TS-1088 / TS-1187A 轻触开关、1206 47µF/10V 陶瓷。
- 基础库的钽电容只有 6.3V，用在 5V 上降额不够（MnO₂ 钽要 50% 降额，失效会短路）→ 用陶瓷。
- 坐标文件按 KiCad 原样导出（Y 为负，和 Gerber 一致）；**旋转角度常有 90°/180° 偏差**，下单后在嘉立创预览里逐个核对二极管、SOT-23、Type-C、LED 的方向。
- 插件件（USB-A、排针）不在 SMT BOM 里，手焊或另选插件服务。

## 协作 / 文件

- 用 Bash/Python 改文件后，工具会提示“文件在磁盘上被修改”——那是自己改的，不是别人；Write 之前要先 Read。
- 脚本里 `pgrep -f`/`pkill -f` 会匹配到自己的 shell（退出码 144），杀进程用 `ps -eo pid,args | awk '/[p]attern/{print $1}'`。
