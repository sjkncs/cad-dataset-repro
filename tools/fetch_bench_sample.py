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
import argparse
import json
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from hf_util import api_tree, fetch_bytes  # noqa: E402

DS = "markov-ai/autocad-bench-tasks"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "bench", "sample")
DEFAULT_TASKS = ["task-001", "task-002"]


def pick_by_type(manifest: str, drawing_type: str, n: int) -> list[str]:
    """从 tasks.jsonl 挑某类型的任务（按 gold 体积升序，取最小的几个，省流量）。"""
    rows = [json.loads(l) for l in open(manifest, encoding="utf-8") if l.strip()]
    sub = sorted([r for r in rows if r["drawing_type"] == drawing_type],
                 key=lambda r: r["gold_bytes"])
    return [r["task_name"] for r in sub[:n]]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tasks", nargs="*", default=None,
                    help="任务名列表（默认 task-001 task-002）")
    ap.add_argument("--by-type", choices=["2d", "3d"], default=None,
                    help="按图纸类型自动挑选任务")
    ap.add_argument("--count", type=int, default=2, help="--by-type 时挑几个")
    ap.add_argument("--max-mb", type=float, default=20.0)
    ap.add_argument("--out", default=OUT)
    args = ap.parse_args()

    if args.tasks:
        tasks = args.tasks
    elif args.by_type:
        manifest = os.path.join(ROOT, "bench", "tasks.jsonl")
        if not os.path.exists(manifest):
            sys.exit("需要 bench/tasks.jsonl，先跑 tools/fetch_bench.py")
        tasks = pick_by_type(manifest, args.by_type, args.count)
        print(f"按类型 {args.by_type} 自动挑选: {tasks}")
    else:
        tasks = DEFAULT_TASKS

    os.makedirs(args.out, exist_ok=True)
    limit = int(args.max_mb * 1024 * 1024)

    print("=" * 74)
    print(f"取 autocad-bench 样件 · {DS}")
    print("=" * 74)

    for task in tasks:
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
            local = os.path.join(args.out, f"{task}__{role}__{fname}")
            if os.path.exists(local) and os.path.getsize(local) > 0:
                print(f"  {role:<6} {fname} 已存在 ({os.path.getsize(local)/1024:.1f} KB)")
                continue
            try:
                data = fetch_bytes(DS, remote, max_bytes=limit)
                if data is None:
                    print(f"  {role:<6} {fname} 超过 {args.max_mb} MB 上限，跳过")
                    continue
                with open(local, "wb") as f:
                    f.write(data)
                print(f"  {role:<6} {fname} -> {os.path.basename(local)}  {len(data)/1024:.1f} KB")
            except Exception as e:
                print(f"  {role:<6} {fname} 失败: {type(e).__name__}: {e}")

    print(f"\n落盘目录: {args.out}")
    total = 0
    for f in sorted(os.listdir(args.out)):
        p = os.path.join(args.out, f)
        sz = os.path.getsize(p)
        total += sz
        print(f"  {f:<44} {sz/1024:9.1f} KB")
    print(f"  合计 {total/1024:.1f} KB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
