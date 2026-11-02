"""
ESP32-C3 双路 MOS 开关板 —— SKiDL 原理图源文件

功能：
  - Type-C 5V 供电 + 原生 USB 烧录/日志（GPIO18/19，无 USB 转串口芯片）
  - 低 Iq LDO（RT9080-33，2µA）给 C3-MINI-1 供电
  - 通道 1（GPIO10）：P-MOS 高边开关 → USB-A 母座，接 5V 2A USB 灯条，支持 PWM
  - 通道 2（GPIO7）：N-MOS 低边开关 → 焊线焊盘，接 ≤0.5A 小电机/LED
  - 需 5V 3A 适配器，两路合计 ≤2.5A
  - BOOT / RST 按键，GPIO8 低电平点亮状态灯
  - 1x08 扩展排针（3V3/GND/IO0/1/3/4/5/6），UART0 测试焊盘，M2 安装孔 ×2

运行：~/tools/cadvenv/bin/python c3_switch_board.py
"""

import os

os.environ.setdefault("KICAD9_SYMBOL_DIR", "/usr/share/kicad/symbols")
os.environ.setdefault("KICAD9_FOOTPRINT_DIR", "/usr/share/kicad/footprints")

from skidl import *  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
set_default_tool(KICAD9)

# PWR_FLAG 等虚拟符号没有封装，不报错
# （`from skidl import *` 会把 skidl 这个名字覆盖成子模块，所以从 sys.modules 取包本体）
import sys  # noqa: E402
_skidl_pkg = sys.modules["skidl"]
_default_fp_handler = _skidl_pkg.empty_footprint_handler
_skidl_pkg.empty_footprint_handler = (
    lambda part: None if part.ref.startswith("#") else _default_fp_handler(part))
lib_search_paths[KICAD9].append(os.path.join(HERE, "lib"))

# ---------------------------------------------------------------- 封装
R0402 = "Resistor_SMD:R_0402_1005Metric"
C0402 = "Capacitor_SMD:C_0402_1005Metric"
C0603 = "Capacitor_SMD:C_0603_1608Metric"
SOD323 = "Diode_SMD:D_SOD-323"

R = Part("Device", "R", footprint=R0402, dest=TEMPLATE)
C = Part("Device", "C", footprint=C0402, dest=TEMPLATE)

# ---------------------------------------------------------------- 网络
vbus = Net("VBUS")      # Type-C 口上的原始 5V
v5 = Net("+5V")         # 过保险丝后的 5V，同时作负载电源
v3 = Net("+3V3")
gnd = Net("GND")
for n in (v5, v3, gnd):
    n.drive = POWER
dp, dm = Net("USB_D+"), Net("USB_D-")
en = Net("EN")
boot = Net("GPIO9_BOOT")
led_n = Net("GPIO8_LED")

# ---------------------------------------------------------------- Type-C
j1 = Part("Connector", "USB_C_Receptacle_USB2.0_16P", ref="J1",
          value="TYPE-C-31-M-12",
          footprint="Connector_USB:USB_C_Receptacle_HRO_TYPE-C-31-M-12")
vbus += j1["VBUS"]
gnd += j1["GND"]
dp += j1["D+"]
dm += j1["D-"]
j1["SBU1", "SBU2"] += NC

# CC 下拉 5.1k，让 C-to-C 适配器输出 5V
r_cc1 = R(ref="R1", value="5.1k")
r_cc2 = R(ref="R2", value="5.1k")
j1["CC1"] & r_cc1 & gnd
j1["CC2"] & r_cc2 & gnd

# 外壳：1M // 4.7nF 接 GND，泄放静电又不形成地环路
r_sh = R(ref="R3", value="1M")
c_sh = C(ref="C1", value="4.7nF")
shield = Net("SHIELD")
shield += j1["SHIELD"], r_sh[1], c_sh[1]
gnd += r_sh[2], c_sh[2]

# USB 数据线 ESD
u2 = Part("Power_Protection", "USBLC6-2SC6", ref="U2", value="USBLC6-2SC6",
          footprint="Package_TO_SOT_SMD:SOT-23-6")
dp += u2["I/O1"]
dm += u2["I/O2"]
vbus += u2["VBUS"]
gnd += u2["GND"]

# VBUS：自恢复保险丝（ESD 钳位由 USBLC6 的 VBUS 脚完成）
f1 = Part("Device", "Polyfuse", ref="F1", value="3A/6V",
          footprint="Fuse:Fuse_1206_3216Metric")
vbus & f1 & v5

# ---------------------------------------------------------------- 5V 储能
# 电机启动 / 灯条 PWM 的冲击会拉低 5V 导致 C3 复位，这里放储能电容（1206 陶瓷，基础库）
c2 = C(ref="C2", value="47uF/10V", footprint="Capacitor_SMD:C_1206_3216Metric")
v5 & c2 & gnd

# ---------------------------------------------------------------- LDO 3.3V
# RT9080-33GJ5：600mA，Iq 2µA，SOT-23-5，国产便宜、可手焊
# 引脚 1 VIN / 2 GND / 3 EN / 4 NC / 5 VOUT，与 TLV755xxPDBV 符号一致；
# ME6211C33M5G 引脚兼容，可作更便宜的替代（Iq 40µA）
u3 = Part("Regulator_Linear", "TLV75533PDBV", ref="U3", value="RT9080-33GJ5",
          footprint="Package_TO_SOT_SMD:SOT-23-5")
v5 += u3["IN"], u3["EN"]
gnd += u3["GND"]
v3 += u3["OUT"]
u3["NC"] += NC
c3 = C(ref="C3", value="10uF", footprint=C0603)
c4 = C(ref="C4", value="10uF", footprint=C0603)
v5 & c3 & gnd
v3 & c4 & gnd

# ---------------------------------------------------------------- ESP32-C3
u1 = Part("Espressif", "ESP32-C3-MINI-1", ref="U1", value="ESP32-C3-MINI-1-N4",
          footprint="PCM_Espressif:ESP32-C3-MINI-1")
v3 += u1["3V3"]
gnd += u1["GND"]
dm += u1["GPIO18/USB_D-"]
dp += u1["GPIO19/USB_D+"]
en += u1["EN/CHIP_PU"]
boot += u1["GPIO9"]
led_n += u1["GPIO8"]

# 模组电源去耦
c5 = C(ref="C5", value="10uF", footprint=C0603)
c6 = C(ref="C6", value="100nF")
v3 & c5 & gnd
v3 & c6 & gnd

# EN：10k 上拉 + 1µF 延时，RST 键对地
r4 = R(ref="R4", value="10k")
c7 = C(ref="C7", value="1uF")
v3 & r4 & en
en & c7 & gnd
sw_rst = Part("Switch", "SW_Push", ref="SW1", value="RST",
              footprint="Button_Switch_SMD:SW_SPST_TS-1088-xR020")
en & sw_rst & gnd

# BOOT：GPIO9 上拉，按住上电/复位进入下载模式
r5 = R(ref="R5", value="10k")
v3 & r5 & boot
sw_boot = Part("Switch", "SW_Push", ref="SW2", value="BOOT",
               footprint="Button_Switch_SMD:SW_SPST_TS-1088-xR020")
boot & sw_boot & gnd

# 启动配置脚：GPIO2、GPIO8 上拉为高
r6 = R(ref="R6", value="10k")
r7 = R(ref="R7", value="10k")
io2 = Net("GPIO2")
io2 += u1["GPIO2/ADC1_CH2"]
v3 & r6 & io2
v3 & r7 & led_n

# 状态灯：GPIO8 输出低点亮，平时不耗电
r8 = R(ref="R8", value="2k")
d2 = Part("Device", "LED", ref="D2", value="Red",
          footprint="LED_SMD:LED_0603_1608Metric")
v3 & r8
d2["A"] += r8[2]
d2["K"] += led_n

# ---------------------------------------------------------------- 通道 1：USB-A 灯条（高边）
# USB 灯条插头外壳常与 GND 相连，所以 USB-A 口的 GND 始终接地，切 +5V（P-MOS 高边）。
# GPIO10 高 → Q1 导通 → Q3 栅极被拉低 → Q3 导通 → USB-A 出 5V。
# Q3 栅极上拉 4.7k，关断时间常数约 3µs，PWM 调光建议 ≤1kHz。
# 注意：GPIO6(MTCK) 复位后默认开内部上拉（EFUSE_DIS_PAD_JTAG=0），与 100k 下拉分压约 2.3V
# 会让 MOS 开机误导通，所以不用 GPIO4~6 做开关；GPIO10、GPIO7 复位后只开输入、无上拉。
ctrl1, gate1, pg1, vout1 = Net("CTRL1"), Net("GATE1"), Net("PGATE1"), Net("VOUT1")
ctrl1 += u1["GPIO10"]
r10 = R(ref="R10", value="100R")
r11 = R(ref="R11", value="100k")   # 上电/深睡时保证关断
ctrl1 & r10 & gate1
gate1 & r11 & gnd
q1 = Part("Transistor_FET", "AO3400A", ref="Q1", value="AO3400A",
          footprint="Package_TO_SOT_SMD:SOT-23")
gate1 += q1["G"]
pg1 += q1["D"]
q1["S"] += gnd

r17 = R(ref="R17", value="4.7k")
v5 & r17 & pg1
q3 = Part("Transistor_FET", "AO3401A", ref="Q3", value="AO3401A",
          footprint="Package_TO_SOT_SMD:SOT-23")
q3["S"] += v5
q3["G"] += pg1
q3["D"] += vout1

# USB-A 母座（插件，卧式），只用 VBUS/GND，数据脚悬空
j2 = Part("Connector", "USB_A", ref="J2", value="DS1095-WNR0",
          footprint="Connector_USB:USB_A_Connfly_DS1095")
vout1 += j2["VBUS"]
gnd += j2["GND"], j2["Shield"]
j2["D+", "D-"] += NC

# ---------------------------------------------------------------- 通道 2：小负载（低边）
# ≤0.5A 小电机 / LED，负载接 J3(1)=+5V、J3(2)=OUT2
ctrl2, gate2, out2 = Net("CTRL2"), Net("GATE2"), Net("OUT2")
ctrl2 += u1["GPIO7"]
r12 = R(ref="R12", value="100R")
r13 = R(ref="R13", value="100k")
ctrl2 & r12 & gate2
gate2 & r13 & gnd
q2 = Part("Transistor_FET", "AO3400A", ref="Q2", value="AO3400A",
          footprint="Package_TO_SOT_SMD:SOT-23")
gate2 += q2["G"]
out2 += q2["D"]
q2["S"] += gnd

# 续流二极管 + 火花吸收（接电机必装，接 LED 可不贴）
d4 = Part("Device", "D_Schottky", ref="D4", value="1N5819WS", footprint=SOD323)
d4["K"] += v5
d4["A"] += out2
c9 = C(ref="C9", value="100nF")
v5 & c9 & out2

# 焊线焊盘（通孔 Ø0.9mm，0.5mm²/AWG20 线），无需物料
j3 = Part("Connector_Generic", "Conn_01x02", ref="J3", value="LOAD2",
          footprint="Connector_Wire:SolderWire-0.5sqmm_1x02_P4.6mm_D0.9mm_OD2.1mm")
j3[1] += v5
j3[2] += out2

# ---------------------------------------------------------------- 扩展 & 调试
j4 = Part("Connector_Generic", "Conn_01x08", ref="J4", value="EXT",
          footprint="Connector_PinHeader_2.54mm:PinHeader_1x08_P2.54mm_Vertical")
j4[1] += v3
j4[2] += gnd
for pin, (name, upin) in zip(range(3, 9), [
    ("GPIO0", "GPIO0/ADC1_CH0/XTAL_32K_P"),
    ("GPIO1", "GPIO1/ADC1_CH1/XTAL_32K_N"),
    ("GPIO3", "GPIO3/ADC1_CH3"),
    ("GPIO4", "GPIO4/ADC1_CH4"),
    ("GPIO5", "GPIO5/ADC2_CH0"),
    ("GPIO6", "GPIO6"),
]):
    n = Net(name)
    n += u1[upin], j4[pin]

for ref, name, upin in [("TP1", "U0RXD", "GPIO20/U0RXD"),
                        ("TP2", "U0TXD", "GPIO21/U0TXD")]:
    tp = Part("Connector", "TestPoint", ref=ref, value=name,
              footprint="TestPoint:TestPoint_Pad_D1.0mm")
    n = Net(name)
    n += u1[upin], tp[1]

# M2 安装孔（对角两个，非金属化）
for ref in ("H1", "H2"):
    Part("Mechanical", "MountingHole", ref=ref, value="M2",
         footprint="MountingHole:MountingHole_2.2mm_M2")

# 电源标记：告诉 KiCad ERC 这些网络由外部（USB）供电；VOUT1 由 Q3 开关供电
for n in (vbus, v5, gnd, vout1):
    Part("power", "PWR_FLAG", dest=TEMPLATE)()[1] += n

# ---------------------------------------------------------------- 立创编号
# 嘉立创 SMT 用；“基础”=基础库，无换料费。2026-11 查询
LCSC = {
    "ESP32-C3-MINI-1-N4": "C2838502",  # 扩展
    "RT9080-33GJ5": "C841192",         # 扩展
    "USBLC6-2SC6": "C2687116",         # 扩展（SOT-23-6，0.8mm 电源线能接入 VBUS 脚）
    "TYPE-C-31-M-12": "C165948",       # 扩展
    "3A/6V": "C883136",                # 扩展 BSMD1206-300-6V
    "AO3400A": "C20917",               # 基础
    "AO3401A": "C15127",               # 基础
    "4.7k": "C25900",                  # 基础 0402
    "DS1095-WNR0": "C19944603",        # 扩展 USB-A 母座（插件，手焊或插件服务）
    "1N5819WS": "C191023",             # 基础
    "Red": "C2286",                    # 基础 KT-0603R
    "RST": "C720477",                  # 基础 TS-1088-AR02016
    "BOOT": "C720477",
    "47uF/10V": "C96123",              # 基础 1206
    "10uF": "C19702",                  # 基础 0603 10V
    "100nF": "C1525",                  # 基础 0402
    "1uF": "C52923",                   # 基础 0402
    "4.7nF": "C1538",                  # 基础 0402
    "5.1k": "C25905",                  # 基础 0402
    "10k": "C25744",
    "100k": "C25741",
    "100R": "C25076",
    "2k": "C4109",
    "1M": "C26083",
}
for part in default_circuit.parts:
    if part.ref.startswith(("#", "TP", "J3", "J4", "H")) or "DNP" in str(part.value):
        continue          # 虚拟符号、焊盘、插件排针、安装孔、不贴件不进 BOM
    part.fields["LCSC"] = LCSC[str(part.value)]

# 模组 NC 脚
for p in u1.pins:
    if p.name == "NC":
        p += NC

if __name__ == "__main__":
    ERC()
    generate_netlist(file_=os.path.join(HERE, "c3_switch_board.net"))
    generate_schematic(filepath=HERE, top_name="c3_switch_board",
                       title="ESP32-C3 双路 MOS 开关板", mode="labels")

    # schematizer 不转 DNP 字段，这里给不贴件补上 KiCad 的 (dnp yes)
    import re
    sch_path = os.path.join(HERE, "c3_switch_board.kicad_sch")
    sch = open(sch_path, encoding="utf-8").read()
    dnp_refs = [p.ref for p in default_circuit.parts if "DNP" in str(p.value)]
    blocks = sch.split("\n  (symbol\n")
    for i, b in enumerate(blocks):
        m = re.search(r'\(property "Reference" "([^"]+)"', b)
        if m and m.group(1) in dnp_refs:
            blocks[i] = b.replace("(dnp no)", "(dnp yes)", 1)
    open(sch_path, "w", encoding="utf-8").write("\n  (symbol\n".join(blocks))
