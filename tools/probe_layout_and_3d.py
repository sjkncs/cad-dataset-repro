#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
probe_layout_and_3d.py — 探查 paper space 布局与 3D 实体构成

上游对交付口径的要求（README 原文）：
  2D 任务：Model Space 里完整的标注图纸
  3D 任务：Model Space 里**真实的 3D 几何** + Layout1 上完整的图纸呈现

所以第 1 层要能回答两个问题：
  Q1 2D/3D 怎么区分？   —— 看 model space 里有没有 3D 实体类型
  Q2 Layout1 有没有内容？ —— 看 paper space 布局里有多少实体

本脚本对 gold 实测，先把事实摆出来，再据此写判定规则。
"""

from __future__ import annotations

import argparse
import collections
import os
import shutil
import subprocess
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
    "PLANESURFACE", "MESH", "POLYFACE", "SUBD", "HELIX",
}
# 只在 3D 语境出现的类型
MAYBE_3D = {"3DFACE", "POLYLINE", "LWPOLYLINE", "SPLINE", "ELLIPSE"}


def analyze(dxf_path: str) -> dict:
    doc = ezdxf.readfile(dxf_path)

    msp = doc.modelspace()
    msp_by_type = collections.Counter(e.dxftype() for e in msp)

    # 所有布局：modelspace 之外就是 paper space 布局
    layouts = []
    for name in doc.layout_names():
        lay = doc.layout(name)
        try:
            ent = list(lay)
        except Exception:  # noqa: BLE001
            ent = []
        by_type = collections.Counter(e.dxftype() for e in ent)
        ext = ezbbox.extents(ent) if ent else None
        bb = None
        if ext is not None and ext.has_data:
            bb = [round(ext.extmin.x, 3), round(ext.extmin.y, 3),
                  round(ext.extmax.x, 3), round(ext.extmax.y, 3)]
        layouts.append({
            "name": name,
            "is_modelspace": name.lower() == "model",
            "entity_count": len(ent),
            "by_type": dict(by_type.most_common()),
            "bbox": bb,
        })

    # 3D 判定：model space 里是否有真三维实体
    solid3d = {t: n for t, n in msp_by_type.items() if t.upper() in SOLID_3D_TYPES}
    # 退化判据：所有实体是否都在 z=0 平面
    zs = set()
    for e in msp:
        try:
            ext = ezbbox.extents([e])
            if ext.has_data:
                zs.add(round(ext.extmin.z, 6))
                zs.add(round(ext.extmax.z, 6))
        except Exception:  # noqa: BLE001
            pass
    flat = all(abs(z) < 1e-6 for z in zs) if zs else None

    return {
        "msp_by_type": dict(msp_by_type.most_common()),
        "msp_entity_count": len(msp),
        "solid_3d_types_present": solid3d,
        "has_true_3d": bool(solid3d),
        "z_values": sorted(zs)[:10],
        "is_flat_at_z0": flat,
        "layouts": layouts,
        "layout_names": doc.layout_names(),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dwg", nargs="+", required=True)
    ap.add_argument("--libredwg", default=None)
    args = ap.parse_args()

    dwg2dxf = find_libredwg(args.libredwg)
    if not dwg2dxf:
        sys.exit("找不到 dwg2dxf，先跑 tools/fetch_libredwg.py")

    for dwg in args.dwg:
        print("=" * 78)
        print(f"{os.path.basename(dwg)}")
        print("=" * 78)
        tmp = tempfile.mkdtemp(prefix="lay_")
        try:
            dxf = dwg_to_dxf(dwg2dxf, dwg, tmp)
            r = analyze(dxf)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

        print(f"  model space 实体 {r['msp_entity_count']} 个")
        print(f"    类型: {r['msp_by_type']}")
        print(f"\n  真三维实体类型: {r['solid_3d_types_present'] or '无'}")
        print(f"  → has_true_3d = {r['has_true_3d']}")
        print(f"  所有实体的 z 值: {r['z_values']}")
        print(f"  → 完全位于 z=0 平面 = {r['is_flat_at_z0']}")

        print(f"\n  布局（{len(r['layout_names'])} 个）: {r['layout_names']}")
        for L in r["layouts"]:
            tag = "MODEL" if L["is_modelspace"] else "PAPER"
            print(f"    [{tag}] {L['name']:<12} 实体 {L['entity_count']:>4}  "
                  f"类型 {L['by_type']}")
            if L["bbox"]:
                print(f"            bbox {L['bbox']}")
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
