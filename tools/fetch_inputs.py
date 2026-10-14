#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fetch_inputs.py — 拉取指定软件分组的 input_files（评测真正需要的东西）

input_files 里有 PDF/DWG/图片，是 L2 评测的输入。
单文件通常几百 KB~几 MB，比 clip.mp4 小几个数量级。

用法：
  python fetch_inputs.py --dataset markov-ai/cad-1000-hours --software sketchup
  python fetch_inputs.py --dataset markov-ai/cad-1000-hours --software sketchup --max-mb 30
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
INPUTS = os.path.join(ROOT, "inputs")


def api_tree(dataset: str, path: str) -> list[dict]:
    url = f"{HF}/api/datasets/{dataset}/tree/{path}"
    with urllib.request.urlopen(url, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))


def download(dataset: str, remote: str, dest: str, max_bytes: int) -> tuple[str, str]:
    if os.path.exists(dest) and os.path.getsize(dest) > 0:
        return remote, "cached"
    try:
        url = f"{HF}/datasets/{dataset}/resolve/main/{remote}"
        req = urllib.request.Request(url, headers={"User-Agent": "cad-repro/1.0"})
        with urllib.request.urlopen(req, timeout=180) as r:
            size = int(r.headers.get("Content-Length") or 0)
            if size and size > max_bytes:
                return remote, f"skip {size/1024/1024:.1f}MB > limit"
            data = r.read()
        if len(data) > max_bytes:
            return remote, f"skip {len(data)/1024/1024:.1f}MB > limit"
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, "wb") as f:
            f.write(data)
        return remote, f"{len(data)/1024:.0f} KB"
    except urllib.error.HTTPError as e:
        return remote, f"HTTP {e.code}"
    except Exception as e:  # noqa: BLE001
        return remote, type(e).__name__


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", required=True)
    ap.add_argument("--software", required=True)
    ap.add_argument("--max-mb", type=float, default=40.0)
    ap.add_argument("--workers", type=int, default=6)
    args = ap.parse_args()
    limit = int(args.max_mb * 1024 * 1024)

    print("=" * 72)
    print(f"拉取输入文件 · {args.dataset} / {args.software}（单文件上限 {args.max_mb} MB）")
    print("=" * 72)

    tasks = [it["path"] for it in api_tree(args.dataset, f"main/{args.software}")
             if it.get("type") == "directory"]
    print(f"任务数: {len(tasks)}")

    jobs: list[tuple[str, str]] = []
    for tpath in tasks:
        tid = tpath.split("/")[-1]
        try:
            files = api_tree(args.dataset, f"main/{tpath}/input_files")
        except Exception as e:  # noqa: BLE001
            print(f"  列目录失败 {tid[:8]}: {e}")
            continue
        for f in files:
            if f.get("type") != "file":
                continue
            remote = f"{tpath}/input_files/{f['path'].split('/')[-1]}"
            local = os.path.join(INPUTS, args.dataset.replace("/", "_"),
                                 args.software, tid, f["path"].split("/")[-1])
            jobs.append((remote, local))

    print(f"待下载 {len(jobs)} 个文件\n")
    results = []
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(download, args.dataset, r, l, limit): (r, l) for r, l in jobs}
        for i, fut in enumerate(as_completed(futs), 1):
            remote, info = fut.result()
            results.append((remote, info))
            if i % 10 == 0 or i == len(jobs):
                print(f"  ...{i}/{len(jobs)}")

    ok = [r for r in results if r[1] not in ("cached",) and not r[1].startswith(("skip", "HTTP"))]
    skipped = [r for r in results if r[1].startswith("skip")]
    failed = [r for r in results if r[1].startswith("HTTP") or r[1] in ("URLError", "TimeoutError")]

    print(f"\n完成：下载 {len(ok)} / 跳过(超限) {len(skipped)} / 失败 {len(failed)}")
    for r in failed[:10]:
        print("  FAIL " + r[0] + "  " + r[1])
    for r in skipped[:10]:
        print("  SKIP " + r[0].split('/')[-1] + "  " + r[1])

    d = os.path.join(INPUTS, args.dataset.replace("/", "_"), args.software)
    if os.path.isdir(d):
        total = sum(os.path.getsize(os.path.join(dp, f))
                    for dp, _, fs in os.walk(d) for f in fs)
        n = sum(len(fs) for _, _, fs in os.walk(d))
        print(f"\n落盘: {d}\n  {n} 个文件，{total/1024/1024:.2f} MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
