# lceda-skill

让 Claude Code 用**嘉立创EDA专业版**把 “我想要一块 X 功能的小板” 一路做到**嘉立创可下单**的 skill：`lceda-pcb`。

- 用桌面客户端自带的官方命令行 `lceda-pro`，以脚本画原理图和 PCB、自动布线、铺铜、DRC、导出 Gerber/BOM/坐标文件
- 元件按立创 C 编号放置，用嘉立创库封装，贴片方向不出错；原生设计可以用嘉立创 EDA 免费打样券
- 也能把现成的 KiCad 工程导入后下单（本机不需要装 KiCad）
- 附下单参数建议、免费券规则、Linux 下单助手的免 sudo 安装方法

> 2.0.0 起移除了 KiCad 全流程插件 `pcb-jlc-pipeline`，只保留嘉立创EDA 路线。需要旧版可检出 tag/提交 `8ce045e`。

## 安装（推荐：npx skills）

用 [skills](https://github.com/vercel-labs/skills) 命令行安装，需要 Node.js ≥ 18：

```bash
# 装到用户级（所有项目可用），指定给 Claude Code
npx skills add wusezhiren/lceda-skill -g -a claude-code

# 只装到当前项目（写入 ./.claude/skills，可随项目提交）
npx skills add wusezhiren/lceda-skill -a claude-code
```

不加 `-a` 会交互选择要装到哪些代理（Claude Code、Cursor、Codex 等）；加 `-y` 跳过确认。
更新、查看、卸载：

```bash
npx skills update lceda-pcb        # 拉取最新版本
npx skills ls -g                    # 查看已装 skill
npx skills remove lceda-pcb -g     # 卸载
```

国内网络慢时可加 npm 镜像：`npx --registry=https://registry.npmmirror.com skills add wusezhiren/lceda-skill -g -a claude-code`。

### 其他方式

Claude Code 插件市场（仍然可用）：

```bash
claude plugin marketplace add wusezhiren/lceda-skill
claude plugin install lceda-pcb@lceda-skill
```

**从旧名 `jlceda-pcb` 升级**：3.0.0 起 skill 改名为 `lceda-pcb`（目录 `skills/lceda-pcb/`，调用名 `/lceda-pcb`），内容不变。旧名不会自动迁移，先卸载再重装：

```bash
npx skills remove jlceda-pcb -g && npx skills add wusezhiren/lceda-skill -g -a claude-code       # npx 安装的
claude plugin uninstall jlceda-pcb@lceda-skill && claude plugin marketplace update lceda-skill \
  && claude plugin install lceda-pcb@lceda-skill                                                 # 插件安装的
```

手动拷贝：

```bash
git clone https://github.com/wusezhiren/lceda-skill.git
cp -r lceda-skill/skills/lceda-pcb ~/.claude/skills/
```

## 前置条件

- Linux / macOS / Windows 桌面，**嘉立创EDA专业版桌面客户端 ≥ 4.1.70**（浏览器版不支持命令行）。
  Linux 可让 Claude 运行 skill 里的 `scripts/setup_lceda.sh`：免 sudo 下载解压到 `~/tools/lceda-pro`。
- 首次启动要**你自己**在客户端窗口里登录嘉立创账号，并下载、导入激活文件（免费）。
- Python 3。基础脚本只用标准库；铺铜后 GND 孤岛分析/寻路、拐角倒角（`gnd_islands.py`、`gnd_route.py`、`chamfer.py`）另需 `pip install shapely numpy matplotlib`。
- 不需要安装任何扩展，也不需要开启“外部交互权限”（文件进出走 base64）。

## 用法

装好后直接对 Claude 说需求即可，例如：

- “用立创EDA画一块 ESP32-C3 板，Type-C 供电烧录，一路 2A USB 开关，做完帮我导出下单文件”
- “板子上再加三个电源输出焊盘”（只改 PCB，不动原理图）
- “把这个 KiCad 工程导入嘉立创EDA，检查 DRC 后准备下单”
- “这块板怎么下单最省钱 / 能不能免费打样”

**下单（上传设计到嘉立创）之前 Claude 会先征求你的同意**；提交和付款由你本人完成。

## 已验证

- 嘉立创EDA专业版 Linux x64 4.1.93：原生路线（按立创编号放器件 → 网络连线 → 导入 PCB → 摆件 → 自动布线 → 铺铜 → DRC 0 错 → 导出）实测通过。
- KiCad 9 工程导入：ESP32-C3 开关板（55×22mm，38 器件 / 352 走线 / 104 过孔，立创编号 32 个），导入后 DRC 0，导出下单文件。
- 嘉立创下单助手 Linux 5.0.69：免 sudo 运行，下单页参数自动填写。

- 2.2.0：ESP32-C3 单路 MOS 开关板（20×33mm 双层，31 器件）铺铜后 GND 碎成 16 处 Connection Error，用 `gnd_islands.py` → `gnd_route.py` → `apply_stitch.js` 修到 DRC 0，`chamfer.py` 倒角 50 处。

实测踩过的坑见 `references/pitfalls.md`；摆件/天线/布线规则见 `references/layout-rules.md`；下单与免费券见 `references/ordering.md`。
