#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
extract_issue_body.py — 从 docs/upstream-issue.md 抽出英文正文，另存为纯正文文件

用途：gh issue create --body-file 需要的是**纯正文**，不能带草稿的外层说明
（元信息表、提交命令、自评等）。手工复制易错，改为程序化抽取。
"""

from __future__ import annotations

import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DOC = os.path.join(HERE, "..", "docs", "upstream-issue.md")
OUT = os.path.join(HERE, "..", "docs", "upstream-issue-body.md")


def main() -> int:
    with open(DOC, "r", encoding="utf-8") as f:
        lines = f.read().split("\n")

    # 正文被包在 `````markdown ... ````` 之间（5 个反引号，因正文内含代码块）
    start = end = None
    for i, ln in enumerate(lines):
        if ln.strip().startswith("````markdown"):
            start = i + 1
            continue
        if start is not None and ln.strip() == "````":
            end = i
            break

    if start is None or end is None:
        print("找不到正文围栏（````markdown ... ````）", file=sys.stderr)
        return 1

    body = "\n".join(lines[start:end]).strip() + "\n"

    # 基本校验
    checks = {
        "长度 > 2000": len(body) > 2000,
        "含标题段": "vectorized fast path" in body,
        "无 PUA 字符": not any(0xE000 <= ord(c) <= 0xF8FF for c in body),
        "无草稿残留(元信息)": "建议标题" not in body,
        "无草稿残留(提交命令)": "gh issue create" not in body,
    }
    print(f"抽取正文: {len(body)} 字符, {body.count(chr(10))} 行")
    ok = True
    for k, v in checks.items():
        print(f"  [{'OK' if v else 'FAIL'}] {k}")
        ok &= bool(v)

    if not ok:
        print("校验未通过，不写出", file=sys.stderr)
        return 1

    with open(OUT, "w", encoding="utf-8", newline="\n") as f:
        f.write(body)
    print(f"\n已写出: {os.path.normpath(OUT)}")

    # 打印首尾各 3 行，便于人工确认
    ls = body.split("\n")
    print("\n--- 首 3 行 ---")
    for x in ls[:3]:
        print("  " + x)
    print("--- 末 3 行 ---")
    for x in ls[-4:-1]:
        print("  " + x)
    return 0


if __name__ == "__main__":
    sys.exit(main())
