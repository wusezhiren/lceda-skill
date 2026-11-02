# lceda-skill

让 Claude Code 把 “我想要一块 X 功能的小板” 一路做到 **嘉立创可下单** 的两个 skill。

| 插件 | 用什么做 | 适合 |
|---|---|---|
| **jlceda-pcb** | 嘉立创EDA专业版桌面客户端自带的官方命令行（`lceda-pro`） | 想在嘉立创直接下单；元件用嘉立创库封装，贴片方向不出错；也能把 KiCad 工程导入后下单 |
| **pcb-jlc-pipeline** | KiCad 9 + SKiDL + Freerouting，全部脚本驱动 | 想要 KiCad 工程文件；完全离线；需要自定义布线流程 |

两者可以接力：先用 pcb-jlc-pipeline 出 KiCad 板，再用 jlceda-pcb 的导入路线导进嘉立创EDA下单。

## 安装

```bash
claude plugin marketplace add wusezhiren/lceda-skill
claude plugin install jlceda-pcb@lceda-skill
claude plugin install pcb-jlc-pipeline@lceda-skill
```

（在 Claude Code 里也可以用 `/plugin marketplace add wusezhiren/lceda-skill`。）更新：

```bash
claude plugin marketplace update lceda-skill
claude plugin update jlceda-pcb@lceda-skill
```

不用插件机制也行，直接拷到用户 skill 目录：

```bash
git clone https://github.com/wusezhiren/lceda-skill.git
cp -r lceda-skill/plugins/jlceda-pcb/skills/jlceda-pcb ~/.claude/skills/
cp -r lceda-skill/plugins/pcb-jlc-pipeline/skills/pcb-jlc-pipeline ~/.claude/skills/
```

## 前置条件

### jlceda-pcb

- Linux / macOS / Windows 桌面，**嘉立创EDA专业版桌面客户端 ≥ 4.1.70**（浏览器版不支持命令行）。
  Linux 可让 Claude 运行 `skills/jlceda-pcb/scripts/setup_lceda.sh`：免 sudo 下载解压到 `~/tools/lceda-pro`。
- 首次启动要**你自己**在客户端窗口里登录嘉立创账号，并下载、导入激活文件（免费）。
- Python 3（`lceda.py` 只用标准库）。
- 不需要安装任何扩展，也不需要开启“外部交互权限”（文件进出走 base64）。

### pcb-jlc-pipeline

- KiCad 9（系统 Python 能 `import pcbnew`，有 `kicad-cli`）
- SKiDL（skill 默认在 `~/tools/cadvenv` 虚拟环境里）
- Java 21 + Freerouting 1.9、乐鑫 KiCad 库：`skills/pcb-jlc-pipeline/scripts/setup_tools.sh` 一键装到 `~/tools`（国内镜像）
- Freerouting 1.9 需要 X 显示（桌面或 `xvfb-run`）

## 用法

装好后直接对 Claude 说需求即可，例如：

- “用立创EDA画一块 ESP32-C3 板，Type-C 供电烧录，两路 MOS 开关，做完帮我导出下单文件”
- “把这个 KiCad 工程导入嘉立创EDA，检查 DRC 后准备下单”
- “帮我设计一块 PCB，要能在嘉立创贴片”（会走 KiCad 全流程）

**下单（上传设计到嘉立创）之前 Claude 会先征求你的同意**；付款、拼板、工艺选项在嘉立创下单页由你完成。

## 已验证

- 嘉立创EDA专业版 Linux x64 4.1.93：原生路线（按立创编号放器件 → 网络连线 → 导入 PCB → 摆件 → 自动布线 → 铺铜 → DRC 0 错 → 导出）和 KiCad 9 工程导入（40 器件 / 277 走线 / 94 过孔，DRC 0 错）均实测通过。
- KiCad 9.0.9：ESP32-C3 双路开关板（30×43mm，双层）从原理图到 DRC 0 违规、导出嘉立创 Gerber/BOM/CPL。

各 skill 的 `references/pitfalls.md` 记录了实测踩过的坑。
