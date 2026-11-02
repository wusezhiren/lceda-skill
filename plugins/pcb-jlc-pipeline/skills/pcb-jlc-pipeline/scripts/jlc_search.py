#!/usr/bin/env python3
"""
嘉立创 SMT 元件库查询（jlcpcb.com 公开接口，无需登录）。

用法：
  python3 jlc_search.py "AO3400A" "RT9080-33GJ5"        # 按型号
  python3 jlc_search.py "@0402 10kΩ" "@Tactile"          # 前缀 @ = 只查基础库
  python3 jlc_search.py C20917                           # 按立创编号核对
  python3 jlc_search.py -n 10 "USB-A"                    # 每个关键词显示 10 条

输出按 基础库 > 优选扩展 > 扩展、库存降序排列：
  编号  库类型  型号  封装  库存  单价(USD，1~49 片)  | 描述

注意：
- 基础库（base）没有换料费；每多一种扩展料，嘉立创加收一次换料费。
- 接口偶尔超时，脚本自带重试；连续失败就换个时间再查。
- 立创商城 wmsc.lcsc.com 的接口会 403，别用。
"""

import json
import sys
import time
import urllib.request

URL = "https://jlcpcb.com/api/overseas-pcb-order/v1/shoppingCart/smtGood/selectSmtComponentList"


def query(keyword, page_size=40, base_only=False):
    body = {"keyword": keyword, "currentPage": 1, "pageSize": page_size}
    if base_only:
        body["componentLibraryType"] = "base"
    req = urllib.request.Request(URL, json.dumps(body).encode(),
                                 {"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"})
    for attempt in range(4):
        try:
            data = json.load(urllib.request.urlopen(req, timeout=40))
            return data["data"]["componentPageInfo"]["list"] or []
        except Exception as e:  # noqa: BLE001
            if attempt == 3:
                print(f"  !! 查询失败: {e}", file=sys.stderr)
                return []
            time.sleep(3)


def lib_label(x):
    if x["componentLibraryType"] == "base":
        return "基础"
    return "优选扩展" if x.get("preferredComponentFlag") else "扩展"


def main(argv):
    show = 6
    if len(argv) >= 2 and argv[0] == "-n":
        show, argv = int(argv[1]), argv[2:]
    if not argv:
        print(__doc__)
        return
    for kw in argv:
        base = kw.startswith("@")
        kw = kw.lstrip("@")
        items = query(kw, base_only=base)
        items.sort(key=lambda x: (x["componentLibraryType"] != "base",
                                  not x.get("preferredComponentFlag"), -x["stockCount"]))
        print(f"=== {kw}{' [仅基础库]' if base else ''}")
        for x in items[:show]:
            price = x["componentPrices"][0]["productPrice"] if x["componentPrices"] else "-"
            print(f"  {x['componentCode']:10s} {lib_label(x):4s} {x['componentModelEn'][:28]:28s} "
                  f"{(x['componentSpecificationEn'] or '')[:14]:14s} 库存{x['stockCount']:>9} ${price} "
                  f"| {(x['describe'] or '')[:80]}")


if __name__ == "__main__":
    main(sys.argv[1:])
