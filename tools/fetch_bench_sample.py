#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fetch_bench_sample.py — 取 autocad-bench 单个任务的产物，供 eval harness 开发

边界纪律（上游 README 明确要求）：
  reference.png  = 给模型看的输入
  gold.dwg       = **评测侧**产物，不得进入模型可见域、不得出现在 prompt 里

本脚本把两者下到 bench/sample/ 下并在文件名上标注角色，
便于后续构建「阳性对照」时清楚哪份是 ground truth。
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from hf_util import api_tree, fetch_bytes  # noqa: E402

DS = "markov-ai/autocad-bench-tasks"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "bench", "sample")
TASKS = ["task-001", "task-002"]
os.makedirs(OUT, exist_ok=True)


def main() -> int:
    print("=" * 74)
    print(f"取 autocad-bench 样件 · {DS}")
    print("=" * 74)

    for task in TASKS:
        print(f"\n[{task}]")
        try:
            items = api_tree(DS, f"main/data/{task}")
        except Exception as e:
            print(f"  列目录失败: {type(e).__name__}: {e}")
            continue
        for x in items:
            name = x["path"].split("/")[-1]
            size = x.get("size") or 0
            print(f"  {x.get('type','?'):<9} {name:<18} {size/1024:9.1f} KB")

        for fname, role in (("reference.png", "INPUT"), ("gold.dwg", "GOLD")):
            remote = f"data/{task}/{fname}"
            local = os.path.join(OUT, f"{task}__{role}__{fname}")
            if os.path.exists(local) and os.path.getsize(local) > 0:
                print(f"  {role:<6} {fname} 已存在 ({os.path.getsize(local)/1024:.1f} KB)")
                continue
            try:
                data = fetch_bytes(DS, remote, max_bytes=20 * 1024 * 1024)
                if data is None:
                    print(f"  {role:<6} {fname} 超过 20 MB 上限，跳过")
                    continue
                with open(local, "wb") as f:
                    f.write(data)
                print(f"  {role:<6} {fname} -> {os.path.basename(local)}  {len(data)/1024:.1f} KB")
            except Exception as e:
                print(f"  {role:<6} {fname} 失败: {type(e).__name__}: {e}")

    print(f"\n落盘目录: {OUT}")
    total = 0
    for f in sorted(os.listdir(OUT)):
        p = os.path.join(OUT, f)
        sz = os.path.getsize(p)
        total += sz
        print(f"  {f:<40} {sz/1024:9.1f} KB")
    print(f"  合计 {total/1024:.1f} KB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
