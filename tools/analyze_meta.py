#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
analyze_meta.py — L1 分析：汇总元数据，并解析 rubrics 的评分维度

产出：
  · 任务难度/时长分布
  · 交付物类型分布
  · rubrics 结构（L2 评测的直接依据）
  · 示例任务全貌
"""

from __future__ import annotations

import json
import os
import sys
from collections import Counter, defaultdict

ROOT = os.path.dirname(os.path.abspath(__file__))
META = os.path.join(ROOT, "meta")


def load(p):
    try:
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def walk_tasks(dataset_dir):
    """返回 [(software, task_id, task_dir)]"""
    out = []
    if not os.path.isdir(dataset_dir):
        return out
    for sw in sorted(os.listdir(dataset_dir)):
        swd = os.path.join(dataset_dir, sw)
        if not os.path.isdir(swd):
            continue
        for tid in sorted(os.listdir(swd)):
            td = os.path.join(swd, tid)
            if os.path.isdir(td):
                out.append((sw, tid, td))
    return out


def analyze(dataset: str, show_sample: bool = False):
    ddir = os.path.join(META, dataset.replace("/", "_"))
    tasks = walk_tasks(ddir)
    print("=" * 74)
    print(f"{dataset}  共 {len(tasks)} 个任务")
    print("=" * 74)
    if not tasks:
        print("  （无数据，先跑 fetch_meta.py）")
        return

    by_sw = Counter()
    domains = Counter()
    apps = Counter()
    deliverable_ext = Counter()
    durations = []
    frames = []
    events = []
    rubric_shapes = Counter()
    rubric_total = []
    missing = Counter()

    sample = None
    for sw, tid, td in tasks:
        by_sw[sw] += 1
        desc = load(os.path.join(td, "task_desc.json"))
        rub = load(os.path.join(td, "rubrics.json"))
        meta = load(os.path.join(td, "metadata.json"))

        for name, obj in (("task_desc", desc), ("rubrics", rub), ("metadata", meta)):
            if obj is None:
                missing[f"{name} 缺失"] += 1

        if isinstance(desc, dict):
            domains[desc.get("domain", "?")] += 1
            apps[desc.get("application", "?")] += 1
            for d in desc.get("deliverables", []) or []:
                deliverable_ext[d.get("format") or d.get("type", "?")] += 1
            if sample is None and sw == "sketchup":
                sample = (sw, tid, desc, rub, meta)

        if isinstance(meta, dict):
            ms = meta.get("total_duration_ms")
            if isinstance(ms, (int, float)):
                durations.append(ms / 1000 / 60)          # 分钟
            tf = meta.get("total_frames")
            if isinstance(tf, (int, float)):
                frames.append(tf)
            ec = meta.get("event_count")
            if isinstance(ec, (int, float)):
                events.append(ec)

        if rub is not None:
            if isinstance(rub, dict):
                rubric_shapes["dict:" + ",".join(sorted(rub.keys())[:4])] += 1
                items = rub.get("criteria") or rub.get("rubrics") or rub.get("items")
                if isinstance(items, list):
                    rubric_total.append(len(items))
            elif isinstance(rub, list):
                rubric_shapes["list"] += 1
                rubric_total.append(len(rub))
            else:
                rubric_shapes[type(rub).__name__] += 1

    print("\n-- 软件分布 --")
    for k, v in by_sw.most_common():
        print(f"   {k:<24} {v}")

    print("\n-- 领域分布 --")
    for k, v in domains.most_common():
        print(f"   {k:<30} {v}")

    print("\n-- 应用 --")
    for k, v in apps.most_common():
        print(f"   {k:<24} {v}")

    print("\n-- 交付物格式 --")
    for k, v in deliverable_ext.most_common(12):
        print(f"   {k:<24} {v}")

    if durations:
        ds = sorted(durations)
        n = len(ds)
        print(f"\n-- 任务时长（分钟，n={n}）--")
        for label, idx in (("最小", 0), ("P25", n // 4), ("中位", n // 2),
                           ("P75", 3 * n // 4), ("最大", n - 1)):
            print(f"   {label:<6} {ds[idx]:.1f}")
        print(f"   合计   {sum(ds)/60:.1f} 小时")
    if frames:
        print(f"\n-- 帧数 --\n   中位 {sorted(frames)[len(frames)//2]:,.0f}  合计 {sum(frames):,.0f}")
    if events:
        print(f"-- 事件数 --\n   中位 {sorted(events)[len(events)//2]:,.0f}  合计 {sum(events):,.0f}")

    print("\n-- rubrics 结构 --")
    for k, v in rubric_shapes.most_common():
        print(f"   {k:<44} {v}")
    if rubric_total:
        rt = sorted(rubric_total)
        print(f"   评分项数: 中位 {rt[len(rt)//2]}  范围 {rt[0]}~{rt[-1]}")

    if missing:
        print("\n-- 缺失文件 --")
        for k, v in missing.most_common():
            print(f"   {k:<24} {v}")

    if show_sample and sample:
        sw, tid, desc, rub, meta = sample
        print("\n" + "=" * 74)
        print(f"示例任务（{sw}）: {tid}")
        print("=" * 74)
        print(json.dumps(desc, ensure_ascii=False, indent=2)[:1800])
        print("\n-- metadata --")
        print(json.dumps(meta, ensure_ascii=False, indent=2))
        print("\n-- rubrics（前 1200 字符）--")
        print(json.dumps(rub, ensure_ascii=False, indent=2)[:1200])


if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else "markov-ai/cad-1000-hours"
    analyze(which, show_sample=("--sample" in sys.argv))
