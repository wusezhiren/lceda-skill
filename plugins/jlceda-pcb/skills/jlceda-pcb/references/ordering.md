# 下单：参数、免费券、下单助手

## 免费打样券（2026-11 实测规则）
- 免费要**先领券**（领券中心 jlc.com/coupons，微信扫码领），下单时在“去选择”里选券才抵扣；不领券按特价收费（2 层 10×10 内 5 片约 ¥20）。
- **喷锡免费券已取消**，只有 OSP 和沉金券 → 用免费券时焊盘喷镀必须选“无铅OSP”。
- 上月 PCB 实付 <20 元：只能领 **EDA 专用券**——**整板必须是嘉立创EDA 原生设计，导入 KiCad/AD 的板子不行**（导入第三方库后从头画是允许的）。想免费就走原生路线。
- 上月实付 ≥20 元且已发货：可领**通用券**，不限画图软件。
- 沉金券：沉金面积 ≤ 整板 20%；EDA 专用沉金券要先通过考试。6 层券只能用于真 6 层板。
- 券领取后 30 天有效、不能更换；不支持拼板、返单、拆单。

## 常用参数（小型 2 层贴片板）
| 项 | 选 | 说明 |
|---|---|---|
| 板材/层数/板厚 | FR-4 / 2 / 1.6 | 尺寸从 Gerber 自动识别 |
| 数量 | 5 | PCB 最少 5 片；贴片数量可少于 5 |
| 焊盘喷镀 | 有铅喷锡（付费单）/ 无铅OSP（用免费券） | OSP 放久焊盘易氧化，手焊件尽快焊 |
| 确认生产稿 | 不需要（DRC 已清零时） | 需要时 3 元，多等一轮 |
| 品质赔付 | 按标准合同常规处理（免费） | 默认勾的是 10 元全额赔付 |
| SMT | 需要，只贴顶层，经济型 | 经济型不做插件，USB-A/排针自己焊 |
| 钢网 | 不需要 | SMT 自带 |
| 确认 DFM | 不需要 | |
下单（提交、付款）必须由用户本人确认；上传设计数据前先征得同意。

## 嘉立创下单助手（Linux）
- 官网下载页 `https://www.jlc.com/portal/appDownloadsWithConfig.html` → `download1.sz-jlc.com/pcAssit/<ver>/JLCPcAssit-linux-x64-<ver>.zip`（5.0.69）。
- 自带 install.sh 要 sudo 装到 /opt；免 sudo：解压到 `~/tools/jlc-assistant`，`chmod +x` 主程序和 .so，用 `--no-sandbox` 启动（chrome-sandbox 没有 setuid），自建 `~/.local/share/applications/*.desktop`。
- 自动化：启动时加 `--remote-debugging-port=9333`，`curl localhost:9333/json` 列页面，用 Node 内置 WebSocket 发 CDP：`Runtime.evaluate` 读页面/执行 JS，`Page.captureScreenshot` 截图（Wayland 下系统截屏不可用，这个可以），`Input.dispatchMouseEvent` 发真实点击。
- 下单页是 Vue + Element：选项用元素 `.click()` 往往无效，按 `getBoundingClientRect()` 中心坐标发真实鼠标点击才生效；下拉框选项只在展开后才渲染。
- 部分选项（品质赔付、确认生产稿）点击后会弹确认框，要在框里再点一次；弹框关掉后可能残留 `.v-modal` 遮罩挡住后续点击，删掉它再继续。
- 点“立即下单”会在新窗口打开下单页（URL 含 `pcbFileId`），后续操作要连到那个页面。
