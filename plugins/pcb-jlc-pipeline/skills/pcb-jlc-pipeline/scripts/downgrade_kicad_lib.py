#!/usr/bin/env python3
"""
把 KiCad 10 格式的符号库（version 2025xxxx）降成 KiCad 9 能读的格式。

症状：kicad-cli 报“在符号库中找不到符号”/ sym export svg 报“无法加载库”，
     而库文件头是 (version 20251024) 之类。GitHub main 分支的乐鑫库就是这样。
做法：删掉 KiCad 9 不认识的 3 个显示属性，版本号改成 20241209。不影响电气信息。

用法：python3 downgrade_kicad_lib.py lib/Espressif.kicad_sym [更多 .kicad_sym ...]
另外：封装里的 3D 模型路径常写成 ${KICAD8_3RD_PARTY}/...，拷进项目后可用 sed 改成
     ${KIPRJMOD}/lib/3d/...
"""

import re
import sys

UNKNOWN_IN_KICAD9 = ("in_pos_files", "duplicate_pin_numbers_are_jumpers", "do_not_autoplace")

for path in sys.argv[1:]:
    s = open(path, encoding="utf-8").read()
    m = re.search(r"\(version (\d+)\)", s)
    ver = int(m.group(1)) if m else 0
    if ver <= 20241209:
        print(f"{path}: version {ver}，无需处理")
        continue
    s = re.sub(r"\n\s*\((%s) \w+\)" % "|".join(UNKNOWN_IN_KICAD9), "", s)
    s = s.replace(m.group(0), "(version 20241209)", 1)
    s = re.sub(r'\(generator_version "[^"]*"\)', '(generator_version "9.0")', s, count=1)
    open(path, "w", encoding="utf-8").write(s)
    print(f"{path}: {ver} → 20241209")
