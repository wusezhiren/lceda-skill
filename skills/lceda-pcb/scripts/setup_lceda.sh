#!/usr/bin/env bash
# 安装嘉立创EDA专业版 Linux 客户端（免 sudo，解压到 ~/tools/lceda-pro），并检查官方命令行是否可用。
# 客户端 ≥ 4.1.70 才内置命令行（lceda-pro <command>）。版本号从官方下载页自动识别。
# 用法：bash setup_lceda.sh [arch]     arch: x64(默认) | arm64 | loong64 | sw64
set -u
arch=${1:-x64}
dest=~/tools/lceda-pro
mkdir -p ~/tools/lceda-pro-dl
cd ~/tools/lceda-pro-dl

if [ ! -x "$dest/lceda-pro" ]; then
    ver=$(curl -sL --max-time 30 https://lceda.cn/page/download | grep -o "lceda-pro-linux-$arch-[0-9.]*\.zip" | head -1)
    [ -n "$ver" ] || { echo "!! 下载页没找到 linux-$arch 安装包"; exit 1; }
    url="https://image.lceda.cn/files/$ver"
    echo "下载 $url"
    # 单连接只有 ~170KB/s，服务器支持 Range：12 段并行
    size=$(curl -sIL "$url" | grep -i content-length | tail -1 | tr -dc 0-9)
    n=12; part=$(( (size + n - 1) / n ))
    for i in $(seq 0 $((n-1))); do
        s=$((i*part)); e=$((s+part-1)); [ $e -ge $size ] && e=$((size-1))
        ( for t in 1 2 3 4 5 6; do
            have=$(stat -c %s "$ver.p$i" 2>/dev/null || echo 0)
            [ "$have" -ge $((e-s+1)) ] && break
            curl -sL --max-time 900 -r $((s+have))-$e "$url" >> "$ver.p$i"
          done ) &
    done
    wait
    cat $(for i in $(seq 0 $((n-1))); do echo "$ver.p$i"; done) > "$ver" && rm -f "$ver".p*
    unzip -tq "$ver" >/dev/null || { echo "!! zip 校验失败"; exit 1; }
    rm -rf x && mkdir x && unzip -q "$ver" -d x && rm -rf "$dest" && mv x/lceda-pro "$dest" && rm -rf x
fi
"$dest/lceda-pro" --help 2>/dev/null | head -1

# 客户端是 Electron 程序，需要 X 显示
if [ -z "${DISPLAY:-}" ]; then
    export DISPLAY=:0
    xa=$(ls /run/user/$(id -u)/.mutter-Xwaylandauth.* 2>/dev/null | head -1)
    [ -n "$xa" ] && export XAUTHORITY=$xa
fi
if ! "$dest/lceda-pro" doctor 2>/dev/null | grep -q '"connected":true'; then
    echo "启动客户端（首次需要用户在窗口里登录并导入激活文件）..."
    nohup "$dest/lceda-pro" >/tmp/lceda-pro.log 2>&1 &
    sleep 15
fi
"$dest/lceda-pro" doctor 2>/dev/null | grep '"ok"'
echo "如果会话窗口标题是 Regist：请用户在窗口里登录嘉立创账号、下载并导入激活文件，完成后再继续。"
