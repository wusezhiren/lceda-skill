#!/usr/bin/env bash
# 一次性准备工具链（幂等，已装的跳过）。全部装到 ~/tools，不需要 sudo。
#   - Java 21 运行时（清华 Adoptium 镜像）     → ~/tools/jre
#   - Freerouting 1.9.0（5MB；2.x 有 65MB，镜像太慢） → ~/tools/freerouting/fr19.jar
#   - 乐鑫官方 KiCad 库                          → ~/tools/kicad-libs/espressif
# 前提：KiCad 9（含 pcbnew Python 模块、kicad-cli）、SKiDL venv（~/tools/cadvenv）已装。
#
# 用法：bash setup_tools.sh

set -u
mkdir -p ~/tools/jre ~/tools/freerouting ~/tools/kicad-libs

# GitHub 下载：依次试镜像，校验成功即停
gh_get() {  # gh_get <github-url> <out> <check-cmd>
    local url=$1 out=$2 check=$3
    for m in "https://gh-proxy.com/" "https://ghfast.top/" "https://ghproxy.net/" ""; do
        for _ in 1 2 3; do
            curl -sL -C - --max-time 200 -o "$out" "${m}${url}"
            eval "$check" >/dev/null 2>&1 && return 0
        done
        rm -f "$out"
    done
    return 1
}

# 1) Java 21
if [ ! -x ~/tools/jre/bin/java ]; then
    base=https://mirrors.tuna.tsinghua.edu.cn/Adoptium/21/jre/x64/linux/
    f=$(curl -s --max-time 30 $base | grep -o 'OpenJDK21U-jre_x64_linux_hotspot_[^"]*\.tar\.gz' | sort -u | tail -1)
    echo "下载 $f"
    curl -sL --max-time 600 -o /tmp/jre21.tgz "$base$f" && tar xzf /tmp/jre21.tgz -C ~/tools/jre --strip-components=1 && rm /tmp/jre21.tgz
fi
~/tools/jre/bin/java -version 2>&1 | head -1

# 2) Freerouting 1.9.0（需要 X 显示：有桌面用 DISPLAY=:0，否则装 xvfb）
if ! unzip -tq ~/tools/freerouting/fr19.jar >/dev/null 2>&1; then
    gh_get https://github.com/freerouting/freerouting/releases/download/v1.9.0/freerouting-1.9.0.jar \
        ~/tools/freerouting/fr19.jar "unzip -tq ~/tools/freerouting/fr19.jar" || echo "!! Freerouting 下载失败"
fi
ls -la ~/tools/freerouting/fr19.jar

# 3) 乐鑫 KiCad 库（含 ESP32-C3/C6/S3 MINI 等模组的符号/封装/3D）
if [ ! -f ~/tools/kicad-libs/espressif/symbols/Espressif.kicad_sym ]; then
    gh_get https://github.com/espressif/kicad-libraries/archive/refs/heads/main.tar.gz \
        /tmp/esp.tgz "gzip -t /tmp/esp.tgz" && mkdir -p ~/tools/kicad-libs/espressif \
        && tar xzf /tmp/esp.tgz -C ~/tools/kicad-libs/espressif --strip-components=1 && rm /tmp/esp.tgz
fi
ls ~/tools/kicad-libs/espressif/symbols/ 2>/dev/null

# 4) KiCad 全局符号库表（首次没开过 GUI 时不存在，kicad-cli ERC 会报一堆库找不到）
cfg=~/.config/kicad/9.0
mkdir -p $cfg
[ -f $cfg/sym-lib-table ] || cp /usr/share/kicad/template/sym-lib-table $cfg/
[ -f $cfg/fp-lib-table ]  || cp /usr/share/kicad/template/fp-lib-table $cfg/

# 显示环境提示
if [ -z "${DISPLAY:-}" ] && ! command -v xvfb-run >/dev/null; then
    xa=$(ls /run/user/$(id -u)/.mutter-Xwaylandauth.* 2>/dev/null | head -1)
    if [ -n "$xa" ]; then
        echo "布线时用桌面显示: export DISPLAY=:0 XAUTHORITY=$xa"
    else
        echo "没有显示环境：请执行  sudo apt install -y xvfb"
    fi
fi
