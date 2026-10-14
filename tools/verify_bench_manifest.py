#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
verify_bench_manifest.py — autocad-bench 第 1 层（确定性校验）离线实现

这一步是评测器可信度的**前提**（第 3 层阳性对照）：
如果连上游给的 gold 都校验不过，那评测器本身有问题，而不是被测系统不行。

本脚本完全离线、不依赖 AutoCAD / ODA / LibreOffice：
  1. 校验已下载产物对 tasks.jsonl 的 sha256 / 字节数是否逐字节一致
  2. 从 DWG 抽出**格式层**事实（版本、字节数、熵）——不是几何，但可复现
  3. 从 reference.png 抽**图像层**事实（尺寸、非白像素占比）——可复现的代理指标
  4. 明确指出哪些评测项**本脚本做不到**（几何探针），避免过度声称

用法：
    python tools/verify_bench_manifest.py --manifest bench/tasks.jsonl \
        --sample bench/sample
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import math
import sys
from collections import Counter


def sha256_of(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def dwg_facts(path: str) -> dict:
    """DWG 格式层事实：版本签名是前 6 字节 ASCII（如 AC1032 = AutoCAD 2018）。"""
    with open(path, "rb") as f:
        blob = f.read()
    ver = blob[:6].decode("ascii", errors="replace")
    counts = Counter(blob)
    total = len(blob)
    ent = -sum((c / total) * math.log2(c / total) for c in counts.values() if c) if total else 0.0
    zeros = counts.get(0, 0)
    return {
        "bytes": total,
        "dwg_version": ver,
        "entropy_bits_per_byte": round(ent, 4),
        "zero_byte_ratio": round(zeros / total, 4) if total else None,
        "sha256": sha256_of(path),
    }


def png_facts(path: str) -> dict:
    """PNG 图像层事实（用标准库解析 IHDR，不依赖 Pillow）。"""
    with open(path, "rb") as f:
        blob = f.read()
    if blob[:8] != b"\x89PNG\r\n\x1a\n":
        return {"error": "not a PNG"}
    # IHDR 紧跟 8 字节签名 + 4 字节长度 + 4 字节类型
    w = int.from_bytes(blob[16:20], "big")
    h = int.from_bytes(blob[20:24], "big")
    bit_depth = blob[24]
    color_type = blob[25]
    facts = {
        "bytes": len(blob),
        "width": w,
        "height": h,
        "bit_depth": bit_depth,
        "color_type": color_type,
        "sha256": sha256_of(path),
    }
    # 若能拿到 Pillow，补一个"非白像素占比"作为可复现的图像代理指标
    try:
        from PIL import Image
        import numpy as np
        im = Image.open(path).convert("L")
        a = np.asarray(im)
        facts["ink_ratio"] = round(float((a < 250).mean()), 4)
        facts["mean_luma"] = round(float(a.mean()), 2)
    except Exception as e:  # noqa: BLE001
        facts["ink_ratio"] = None
        facts["pillow_note"] = f"{type(e).__name__}"
    return facts


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", default=os.path.join("bench", "tasks.jsonl"))
    ap.add_argument("--sample", default=os.path.join("bench", "sample"))
    ap.add_argument("--json-out", default=None)
    args = ap.parse_args()

    if not os.path.exists(args.manifest):
        sys.exit(f"找不到 manifest: {args.manifest}\n"
                 f"先跑：python tools/fetch_bench.py")

    tasks = {}
    with open(args.manifest, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                r = json.loads(line)
                tasks[r["task_name"]] = r

    print("=" * 76)
    print("autocad-bench 第 1 层确定性校验（离线）")
    print(f"  manifest: {args.manifest}  ({len(tasks)} 个任务)")
    print(f"  sample  : {args.sample}")
    print("=" * 76)

    results = []
    checked = 0
    for fname in sorted(os.listdir(args.sample)) if os.path.isdir(args.sample) else []:
        # 命名约定：<task>__<ROLE>__<原文件名>
        parts = fname.split("__")
        if len(parts) != 3:
            print(f"\n[跳过] {fname}（不符合 <task>__<ROLE>__<name> 约定）")
            continue
        task_name, role, orig = parts
        rec = tasks.get(task_name)
        if rec is None:
            print(f"\n[跳过] {fname}（manifest 中无 {task_name}）")
            continue

        path = os.path.join(args.sample, fname)
        print(f"\n[{task_name} / {role}] {orig}")

        if orig == "reference.png":
            exp_sha, exp_bytes = rec["reference_sha256"], rec["reference_bytes"]
        elif orig == "gold.dwg":
            exp_sha, exp_bytes = rec["gold_sha256"], rec["gold_bytes"]
        else:
            print("  未知产物名，跳过校验")
            continue

        actual_bytes = os.path.getsize(path)
        ok_bytes = actual_bytes == exp_bytes
        print(f"  字节数  期望 {exp_bytes:>9}  实际 {actual_bytes:>9}  "
              f"{'✅' if ok_bytes else '❌'}")

        actual_sha = sha256_of(path)
        ok_sha = actual_sha == exp_sha
        print(f"  sha256  期望 {exp_sha[:16]}…  实际 {actual_sha[:16]}…  "
              f"{'✅' if ok_sha else '❌'}")

        if orig.endswith(".dwg"):
            f = dwg_facts(path)
            print(f"  DWG 版本 {f['dwg_version']}（manifest 未记录版本，"
                  f"上游 README 称 AC1032）  熵 {f['entropy_bits_per_byte']} bit/B")
            if f["dwg_version"] != "AC1032":
                print("      ⚠️ 与 README 声明的 AC1032 不符")
        else:
            f = png_facts(path)
            print(f"  图像     {f.get('width')}x{f.get('height')}  "
                  f"bit_depth={f.get('bit_depth')}  非白占比 {f.get('ink_ratio')}  "
                  f"平均亮度 {f.get('mean_luma')}")

        checked += 1
        results.append({
            "task": task_name, "role": role, "file": orig,
            "bytes_ok": ok_bytes, "sha256_ok": ok_sha,
            "facts": f,
        })

    print("\n" + "=" * 76)
    n_ok = sum(1 for r in results if r["bytes_ok"] and r["sha256_ok"])
    print(f"校验结果: {n_ok}/{checked} 个产物与 manifest 逐字节一致")
    if checked and n_ok == checked:
        print("✅ 阳性对照通过：上游 gold 在本校验器下完全可信")
    elif checked:
        print("❌ 存在不一致 —— 要么下载损坏，要么 manifest 有误")

    print("\n本脚本**做不到**的（不要据此声称评测完备）：")
    print("  · DWG 内部几何（实体计数 / 图层 / 尺寸标注）——需 AutoCAD、ODA 或转 DXF")
    print("  · 2D 标注完整性、3D 实体性、Layout1 图纸完整性")
    print("  · 任何需要 LLM/视觉判断的语义需求")
    print("  → 这些属第 1 层之外，见 bench/EVAL_DESIGN.md 的分层设计")

    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as f:
            json.dump({"checked": checked, "ok": n_ok, "results": results},
                      f, ensure_ascii=False, indent=2)
        print(f"\n报告已写出: {args.json_out}")

    return 0 if (not checked or n_ok == checked) else 1


if __name__ == "__main__":
    sys.exit(main())
