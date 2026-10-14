#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fetch_meta.py — L1：拉取 Markov 两个 CAD 数据集的文本元数据

只下载小文件（task_desc / rubrics / metadata / narration），
**跳过 clip.mp4（百 MB~GB）与 frame_events.json（百 MB）**，避免占满磁盘。

用法：
  python fetch_meta.py --dataset cad-1000-hours --software sketchup
  python fetch_meta.py --dataset cad-environments --all
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

HF = "https://huggingface.co"
ROOT = os.path.dirname(os.path.abspath(__file__))
META = os.path.join(ROOT, "meta")

# 需要的小文件（相对任务目录）
WANTED = ("task_desc.json", "rubrics.json", "metadata.json")

# 明确跳过的巨型文件
SKIP = ("clip.mp4", "frame_events.json", "events.json")


def api_tree(dataset: str, path: str = "main") -> list[dict]:
    url = f"{HF}/api/datasets/{dataset}/tree/{path}"
    with urllib.request.urlopen(url, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))


def raw_url(dataset: str, path: str) -> str:
    return f"{HF}/datasets/{dataset}/resolve/main/{path}"


def fetch_json(dataset: str, path: str, dest: str, retries: int = 3) -> tuple[str, bool, str]:
    """下载单个 JSON 文件，返回 (path, ok, info)。"""
    if os.path.exists(dest) and os.path.getsize(dest) > 2:
        return path, True, "cached"
    for attempt in range(retries):
        try:
            req = urllib.request.Request(raw_url(dataset, path),
                                         headers={"User-Agent": "cad-repro/1.0"})
            with urllib.request.urlopen(req, timeout=90) as r:
                data = r.read()
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with open(dest, "wb") as f:
                f.write(data)
            return path, True, f"{len(data)} B"
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return path, False, "404"
            if attempt == retries - 1:
                return path, False, f"HTTP {e.code}"
        except Exception as e:  # noqa: BLE001
            if attempt == retries - 1:
                return path, False, f"{type(e).__name__}"
    return path, False, "unknown"


def collect_tasks(dataset: str, software: str) -> list[str]:
    """列出某软件下的全部任务 ID。"""
    items = api_tree(dataset, f"main/{software}")
    return [it["path"] for it in items if it.get("type") == "directory"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", required=True)
    ap.add_argument("--software", action="append", default=[])
    ap.add_argument("--all", action="store_true", help="全部软件分组")
    ap.add_argument("--workers", type=int, default=12)
    args = ap.parse_args()

    print("=" * 72)
    print(f"L1 元数据拉取 · {args.dataset}")
    print("=" * 72)

    root_items = api_tree(args.dataset, "main")
    softwares = [it["path"] for it in root_items if it.get("type") == "directory"]
    if not args.all and args.software:
        softwares = [s for s in softwares if s in args.software]
    print(f"软件分组: {softwares}")

    tasks: list[tuple[str, str]] = []
    for sw in softwares:
        ids = collect_tasks(args.dataset, sw)
        print(f"  {sw:<22} {len(ids)} 个任务")
        tasks += [(sw, t) for t in ids]

    # 组装下载清单（三层目录结构：<dataset>/<software>/<task>/<file>）
    jobs: list[tuple[str, str]] = []          # (remote_path, local_path)
    outdir = os.path.join(META, args.dataset.replace("/", "_"))
    for sw, path in tasks:
        task_id = path.split("/")[-1]
        for fn in WANTED:
            remote = f"{path}/{fn}"
            local = os.path.join(outdir, sw, task_id, fn)
            jobs.append((remote, local))

    print(f"\n待下载 {len(jobs)} 个文件（已跳过 {', '.join(SKIP)}）")
    ok = fail = 0
    failures: list[str] = []
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(fetch_json, args.dataset, r, l): r for r, l in jobs}
        done = 0
        for fut in as_completed(futs):
            path, good, info = fut.result()
            done += 1
            if good:
                ok += 1
            else:
                fail += 1
                failures.append(f"{path} ({info})")
            if done % 50 == 0:
                print(f"  ...{done}/{len(jobs)}")

    print(f"\n完成：成功 {ok} / 失败 {fail}")
    if failures:
        print("失败清单（前 20）:")
        for f in failures[:20]:
            print("  " + f)

    total = sum(os.path.getsize(os.path.join(dp, f))
                for dp, _, fs in os.walk(outdir) for f in fs)
    print(f"\n落盘目录: {outdir}")
    print(f"总体积: {total/1024/1024:.2f} MB")
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
