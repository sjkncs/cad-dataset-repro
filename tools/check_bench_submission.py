#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
check_bench_submission.py — autocad-bench 提交物合规判定（第 1 层正式版）

上游对交付口径的原文要求：
  2D 任务：Model Space 里**完整标注的图纸**
  3D 任务：Model Space 里**真实 3D 几何** + `Layout1` 上**完整的图纸呈现**

本脚本把这两条变成可判定的规则。规则来源不是猜的，而是对上游 gold 实测得出：

  | 判据                | 2D gold (001/002) | 3D gold (023/027) |
  |---------------------|-------------------|-------------------|
  | model space 实体数   | 25 / 47           | 2 / 2             |
  | 真三维实体           | 无                | 3DSOLID ×1        |
  | Layout1 实体数       | 0                 | 30 / 35（含 VIEWPORT 7）|

所以：
  · `has_true_3d` 为 3D 任务的必要条件
  · `Layout1` 有实质内容（≥1 VIEWPORT + 若干标注）为 3D 任务的必要条件
  · 2D 任务则要求 model space 有标注（DIMENSION>0）且无 3D 实体

用法：
    python tools/check_bench_submission.py --dwg <candidate.dwg> --expect 3d \
        [--libredwg DIR] [--gold <gold.dwg>]
"""

from __future__ import annotations

import argparse
import collections
import json
import os
import shutil
import sys
import tempfile

import ezdxf
from ezdxf import bbox as ezbbox

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from probe_dwg_geometry import find_libredwg, dwg_to_dxf  # noqa: E402

# 真正的三维实体类型（AutoCAD 语义）
SOLID_3D_TYPES = {
    "3DSOLID", "BODY", "REGION", "SURFACE", "EXTRUDEDSURFACE",
    "LOFTEDSURFACE", "REVOLVEDSURFACE", "SWEPTSURFACE", "NURBSURFACE",
    "PLANESURFACE", "MESH", "SUBFACE", "SUBD", "HELIX",
}


def analyze(dxf_path: str) -> dict:
    doc = ezdxf.readfile(dxf_path)

    def stat(layout, label):
        try:
            ents = list(layout)
        except Exception:  # noqa: BLE001
            ents = []
        by_type = collections.Counter(e.dxftype() for e in ents)
        ext = ezbbox.extents(ents) if ents else None
        bb = None
        if ext is not None and ext.has_data:
            bb = [round(ext.extmin.x, 3), round(ext.extmin.y, 3),
                  round(ext.extmax.x, 3), round(ext.extmax.y, 3)]
        return {"label": label, "count": len(ents),
                "by_type": dict(by_type.most_common()), "bbox": bb}

    msp = stat(doc.modelspace(), "modelspace")
    layouts = []
    for name in doc.layout_names():
        if name.lower() == "model":
            continue
        layouts.append(stat(doc.layout(name), name))

    solid3d = {t: n for t, n in msp["by_type"].items()
               if t.upper() in SOLID_3D_TYPES}

    # z 平面性（仅对能取到 extents 的实体有意义）
    zs = set()
    for e in doc.modelspace():
        try:
            ex = ezbbox.extents([e])
            if ex.has_data:
                zs.add(round(ex.extmin.z, 6))
                zs.add(round(ex.extmax.z, 6))
        except Exception:  # noqa: BLE001
            pass
    flat = all(abs(z) < 1e-6 for z in zs) if zs else None

    # 找到 Layout1（名字可能带空格/大小写差异）
    l1 = next((L for L in layouts if L["label"].strip().lower() == "layout1"), None)

    return {
        "dxf_version": doc.dxfversion,
        "insunits": doc.header.get("$INSUNITS"),
        "layers": sorted(l.dxf.name for l in doc.layers),
        "modelspace": msp,
        "layouts": layouts,
        "has_true_3d": bool(solid3d),
        "solid_3d_types": solid3d,
        "is_flat_at_z0": flat,
        "layout1": l1,
        "layout1_viewports": (l1["by_type"].get("VIEWPORT", 0) if l1 else 0),
        "layout1_entity_count": (l1["count"] if l1 else 0),
        "msp_dimensions": msp["by_type"].get("DIMENSION", 0),
    }


def judge(r: dict, expect: str) -> tuple[bool, list[dict]]:
    """按上游口径判定。返回 (通过?, 逐条依据)。"""
    checks = []

    def add(name, ok, detail):
        checks.append({"check": name, "pass": bool(ok), "detail": str(detail)})
        return bool(ok)

    if expect == "3d":
        add("Model Space 含真实 3D 几何", r["has_true_3d"],
            f"3D 实体类型={r['solid_3d_types'] or '无'}")
        add("Layout1 存在", r["layout1"] is not None,
            f"布局={[L['label'] for L in r['layouts']]}")
        add("Layout1 有视口（VIEWPORT）", r["layout1_viewports"] > 0,
            f"VIEWPORT={r['layout1_viewports']}")
        add("Layout1 有标注（图纸呈现）", r["layout1_entity_count"] > 0,
            f"实体数={r['layout1_entity_count']} 类型={r['layout1']['by_type'] if r['layout1'] else None}")
    else:  # 2d
        add("无 3D 实体（2D 任务不应有）", not r["has_true_3d"],
            f"3D 实体类型={r['solid_3d_types'] or '无'}")
        add("Model Space 含标注（DIMENSION）", r["msp_dimensions"] > 0,
            f"DIMENSION={r['msp_dimensions']}")
        add("Model Space 有实质几何", r["modelspace"]["count"] > 0,
            f"实体数={r['modelspace']['count']}")

    return all(c["pass"] for c in checks), checks


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dwg", required=True)
    ap.add_argument("--expect", choices=["2d", "3d"], default=None,
                    help="按任务类型判定；省略则只输出事实不判定")
    ap.add_argument("--libredwg", default=None)
    ap.add_argument("--json-out", default=None)
    args = ap.parse_args()

    if not os.path.exists(args.dwg):
        sys.exit(f"找不到 {args.dwg}")
    dwg2dxf = find_libredwg(args.libredwg)
    if not dwg2dxf:
        sys.exit("找不到 dwg2dxf，先跑 tools/fetch_libredwg.py")

    tmp = tempfile.mkdtemp(prefix="chk_")
    try:
        dxf = dwg_to_dxf(dwg2dxf, args.dwg, tmp)
        r = analyze(dxf)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("=" * 78)
    print(f"提交物合规判定: {os.path.basename(args.dwg)}"
          + (f"   (期望类型: {args.expect})" if args.expect else ""))
    print("=" * 78)
    print(f"  单位        : $INSUNITS = {r['insunits']}")
    print(f"  图层({len(r['layers'])})    : {r['layers']}")
    print(f"  model space : {r['modelspace']['count']} 实体  {r['modelspace']['by_type']}")
    print(f"  真三维      : {r['has_true_3d']}  {r['solid_3d_types'] or ''}")
    print(f"  完全平面z=0 : {r['is_flat_at_z0']}")
    for L in r["layouts"]:
        print(f"  [{L['label']:<9}] {L['count']:>4} 实体  {L['by_type']}")

    ok = None
    if args.expect:
        ok, checks = judge(r, args.expect)
        print("\n  --- 判定依据 ---")
        for c in checks:
            print(f"    [{'PASS' if c['pass'] else 'FAIL'}] {c['check']}")
            print(f"           {c['detail']}")
        print(f"\n  → 结果: {'✅ 符合 ' + args.expect + ' 任务口径' if ok else '❌ 不符合'}")

    if args.json_out:
        out = dict(r)
        if args.expect:
            out["judgement"] = {"expect": args.expect, "pass": ok, "checks": checks}
        with open(args.json_out, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=2)
        print(f"\n  报告: {args.json_out}")

    return 0 if (ok is None or ok) else 1


if __name__ == "__main__":
    sys.exit(main())
