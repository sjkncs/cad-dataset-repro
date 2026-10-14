#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
rubric_probe.py — 分析 rubrics 的可机器判定程度

结论决定 L2 的架构：rubrics 若大多是自然语言需求，
就必须用 LLM/视觉裁判；若相当比例能提取成结构化断言，
就能做确定性几何校验（更可靠、可复现）。

本脚本把每条 rubric 按「能否提取出可计算量」分类打标，并统计比例。
"""

from __future__ import annotations

import json
import os
import re
import sys
from collections import Counter

ROOT = os.path.dirname(os.path.abspath(__file__))
META = os.path.join(ROOT, "meta", "markov-ai_cad-1000-hours")

# 可机器判定的模式：数量、尺寸、枚举名
PATTERNS = {
    "数量(bay/slot/room 等 + 数字)": re.compile(
        r"\b(\d+)\s+(?:marked\s+)?(?:car\s+)?(?:parking\s+)?"
        r"(bays?|slots?|spaces?|rooms?|floors?|storeys?|stories?|doors?|windows?|"
        r"columns?|beams?|stairs?|steps?|units?|apartments?|rows?|beds?)\b", re.I),
    "显式尺寸(数字+单位)": re.compile(
        r"\b\d+(?:\.\d+)?\s*(?:mm|cm|m|ft|feet|inch|in|square\s*(?:feet|metres|meters)|"
        r"m2|sqm|sq\s*ft)\b", re.I),
    "标高/层数(storey/level)": re.compile(
        r"\b(storey|storeys|stories|levels?|floor\s+to\s+floor|ceiling\s+height)\b", re.I),
    "存在性(exists/includes/contains)": re.compile(
        r"\b(shall\s+(?:be|include|provide|contain)|includes?|contains?|consists?\s+of)\b", re.I),
    "材质/颜色命名": re.compile(
        r"\b(colou?r|material|texture|paint|render|finish|striping|hatch)\b", re.I),
    "命名/标注": re.compile(
        r"\b(named?|labell?ed|tagged|annotat|dimension\s+text|title\s+block)\b", re.I),
    "单位制": re.compile(r"\b(imperial|metric|units?\s+of\s+measure)\b", re.I),
    "空间关系(adjacent/within/flanking)": re.compile(
        r"\b(adjacent|within|inside|flanking|along|between|above|below|opposite|facing)\b", re.I),
    "坡度/倾斜": re.compile(r"\b(slope|sloping|ramp|gradient|inclined|pitched)\b", re.I),
}


def load(p):
    try:
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def main():
    only = sys.argv[1] if len(sys.argv) > 1 else "sketchup"
    ddir = os.path.join(META, only)
    if not os.path.isdir(ddir):
        print(f"目录不存在: {ddir}")
        return 1

    tasks = sorted(d for d in os.listdir(ddir) if os.path.isdir(os.path.join(ddir, d)))
    tag_counter = Counter()
    per_rubric_tags = []
    n_rubrics = 0
    examples = {}

    for tid in tasks:
        rub = load(os.path.join(ddir, tid, "rubrics.json"))
        if not isinstance(rub, dict):
            continue
        items = rub.get("rubrics") or []
        for it in items:
            req = (it.get("requirement") or "").strip()
            if not req:
                continue
            n_rubrics += 1
            hits = [name for name, rx in PATTERNS.items() if rx.search(req)]
            for h in hits:
                tag_counter[h] += 1
                examples.setdefault(h, []).append(f"{tid[:8]}: {req[:110]}")
            per_rubric_tags.append(hits)

    print("=" * 74)
    print(f"rubrics 可判定性分析 · {only} · {len(tasks)} 个任务 / {n_rubrics} 条 rubric")
    print("=" * 74)

    print("\n-- 模式命中次数（一条 rubric 可命中多个）--")
    for name, cnt in tag_counter.most_common():
        pct = cnt / n_rubrics * 100 if n_rubrics else 0
        print(f"   {name:<38} {cnt:>4}  ({pct:5.1f}%)")

    if per_rubric_tags:
        has_any = sum(1 for t in per_rubric_tags if t)
        multi = sum(1 for t in per_rubric_tags if len(t) >= 2)
        print(f"\n-- 覆盖情况 --")
        print(f"   至少命中一个模式: {has_any}/{n_rubrics} = {has_any/n_rubrics*100:.1f}%")
        print(f"   命中两个及以上:   {multi}/{n_rubrics} = {multi/n_rubrics*100:.1f}%")
        nonlocal_count = Counter(len(t) for t in per_rubric_tags)
        print("   命中数分布: " + ", ".join(f"{k}个:{v}" for k, v in sorted(nonlocal_count.items())))

    print("\n-- 各类样例 --")
    for name in ("数量(bay/slot/room 等 + 数字)", "显式尺寸(数字+单位)", "空间关系(adjacent/within/flanking)"):
        if name in examples:
            print(f"\n   [{name}]")
            for e in examples[name][:4]:
                print(f"     · {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
