#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fetch_bench.py — 拉取 autocad-bench-tasks 的评测定义（纯文本，约 35 KB）

只拉评测定义（tasks.jsonl / checksums.sha256 / README.md），
不拉 reference.png 与 gold.dwg，便于在无大磁盘环境检视基准设计。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from hf_util import api_tree, fetch_bytes  # noqa: E402

DS = "markov-ai/autocad-bench-tasks"
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bench")
os.makedirs(OUT, exist_ok=True)

print("=" * 70)
print(DS)
print("=" * 70)

# 根文件
for it in api_tree(DS, "main"):
    p = it.get("path")
    if it.get("type") == "file":
        size = it.get("size") or 0
        print(f"  {p:<24} {size/1024:9.1f} KB")
        if size < 20 * 1024 * 1024 and p not in (".gitattributes",):
            try:
                data = fetch_bytes(DS, p, max_bytes=20 * 1024 * 1024)
                if data:
                    dst = os.path.join(OUT, p.replace("/", "_"))
                    with open(dst, "wb") as f:
                        f.write(data)
                    print(f"      -> 已下载 {len(data)/1024:.1f} KB")
            except Exception as e:
                print(f"      -> 失败 {type(e).__name__}")

# prompts / data 目录
for sub in ("prompts", "data"):
    try:
        items = api_tree(DS, f"main/{sub}")
        print(f"\n  [{sub}] {len(items)} 项")
        for it in items[:8]:
            print(f"     {it.get('type','?'):<10} {it.get('path')}  {it.get('size',0)/1024:.1f} KB")
    except Exception as e:
        print(f"\n  [{sub}] 列目录失败: {type(e).__name__}")

print(f"\n落盘: {OUT}")
for f in sorted(os.listdir(OUT)):
    print(f"  {f}  {os.path.getsize(os.path.join(OUT, f))/1024:.1f} KB")
