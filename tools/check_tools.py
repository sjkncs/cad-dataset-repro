#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""check_tools.py — 提交前自检：tools/ 下所有脚本语法正确、可解析。"""
import ast
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
bad = 0
n = 0
for f in sorted(os.listdir(HERE)):
    if not f.endswith(".py"):
        continue
    n += 1
    p = os.path.join(HERE, f)
    try:
        with open(p, encoding="utf-8") as fh:
            src = fh.read()
        ast.parse(src, filename=p)
        print(f"  OK   {f:<34} {len(src.splitlines()):>4} 行")
    except SyntaxError as e:
        bad += 1
        print(f"  FAIL {f:<34} {e}")

print()
print(f"{n} 个脚本，{bad} 个失败")
sys.exit(1 if bad else 0)
