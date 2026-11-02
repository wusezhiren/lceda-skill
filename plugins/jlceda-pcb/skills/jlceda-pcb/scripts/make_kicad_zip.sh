#!/usr/bin/env bash
# 把 KiCad 工程打成嘉立创EDA能导入的 zip：文件放在 zip 根目录、去掉 3D 模型（控制 base64 后 < 1MB）
# 用法：make_kicad_zip.sh <KiCad工程目录> <输出.zip>
set -e
src=$(cd "$1" && pwd); out=$(realpath -m "$2")
tmp=$(mktemp -d)
( cd "$src" && cp -r *.kicad_pro *.kicad_sch *.kicad_pcb "$tmp"/ && for f in sym-lib-table fp-lib-table; do [ -f $f ] && cp $f "$tmp"/; done
  [ -d lib ] && rsync -a --exclude '3d' --exclude '*.step' --exclude '*.STEP' --exclude '*.wrl' lib "$tmp"/ ) || true
rm -f "$out"; ( cd "$tmp" && zip -qr "$out" . )
rm -rf "$tmp"
sz=$(stat -c %s "$out"); echo "$out  $sz 字节（base64 约 $((sz*4/3/1024)) KB，上限 ~1000 KB）"
