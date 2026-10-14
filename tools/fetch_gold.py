#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fetch_gold.py — 拉取标准答案（gold output）文件

用途：L2 评测器的**阳性对照**。
      如果评测器连作者本人的正确交付物都判不通过，说明评测器本身有问题，
      而不是被测系统不行。这是评测有效性的前提。

用法：
  python fetch_gold.py --dataset markov-ai/cad-1000-hours --software sketchup --limit 3
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

from hf_util import api_tree, fetch_bytes

HF = "https://huggingface.co"
ROOT = os.path.dirname(os.path.abspath(__file__))
GOLD = os.path.join(ROOT, "gold")


def download(dataset: str, remote: str, dest: str, max_bytes: int):
    if os.path.exists(dest) and os.path.getsize(dest) > 0:
        return remote, "cached", os.path.getsize(dest)
    try:
        data = fetch_bytes(dataset, remote, tries=5, timeout=300, max_bytes=max_bytes)
        if data is None:
            return remote, f"skip >{max_bytes/1024/1024:.0f}MB", 0
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, "wb") as f:
            f.write(data)
        return remote, f"{len(data)/1024/1024:.2f} MB", len(data)
    except urllib.error.HTTPError as e:
        return remote, f"HTTP {e.code}", 0
    except Exception as e:  # noqa: BLE001
        return remote, f"{type(e).__name__}", 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", required=True)
    ap.add_argument("--software", required=True)
    ap.add_argument("--limit", type=int, default=3, help="只取前 N 个任务")
    ap.add_argument("--max-mb", type=float, default=60.0)
    ap.add_argument("--ext", default=".skp", help="只要该后缀的交付物")
    ap.add_argument("--workers", type=int, default=3)
    args = ap.parse_args()
    limit_b = int(args.max_mb * 1024 * 1024)

    print("=" * 72)
    print(f"拉取标准答案 · {args.dataset} / {args.software}（前 {args.limit} 个任务，{args.ext}）")
    print("=" * 72)

    tasks = [it["path"] for it in api_tree(args.dataset, f"main/{args.software}")
             if it.get("type") == "directory"]
    print(f"任务总数 {len(tasks)}，本轮取 {min(args.limit, len(tasks))}")

    jobs = []
    for tpath in tasks[: args.limit]:
        tid = tpath.split("/")[-1]
        try:
            files = api_tree(args.dataset, f"main/{tpath}/output_files")
        except Exception as e:  # noqa: BLE001
            print(f"  列目录失败 {tid[:8]}: {e}")
            continue
        for f in files:
            if f.get("type") != "file":
                continue
            name = f["path"].split("/")[-1]
            if args.ext and not name.lower().endswith(args.ext):
                continue
            remote = f"{tpath}/output_files/{name}"
            local = os.path.join(GOLD, args.dataset.replace("/", "_"),
                                 args.software, tid, name)
            jobs.append((remote, local, f.get("size") or 0))

    print(f"待下载 {len(jobs)} 个交付物\n")
    for r, l, s in jobs:
        print(f"  {r.split('/')[-1]:<24} {s/1024/1024:7.2f} MB  ->  {l.split(os.sep)[-2][:8]}")

    results = []
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = [ex.submit(download, args.dataset, r, l, limit_b) for r, l, _ in jobs]
        for fut in as_completed(futs):
            results.append(fut.result())

    print()
    for remote, info, size in results:
        print(f"  {remote.split('/')[-1]:<24} {info}")

    d = os.path.join(GOLD, args.dataset.replace("/", "_"), args.software)
    if os.path.isdir(d):
        total = sum(os.path.getsize(os.path.join(dp, f))
                    for dp, _, fs in os.walk(d) for f in fs)
        print(f"\n落盘: {d}\n  {total/1024/1024:.2f} MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
