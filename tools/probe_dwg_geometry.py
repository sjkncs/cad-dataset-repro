#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
probe_dwg_geometry.py — 第 1 层几何探针（DWG → DXF → ezdxf）

链路：libredwg `dwg2dxf` 转 DXF（开源、免注册）→ ezdxf 读 → 抽确定性几何事实。
这是第 1 层从「格式层」升级到「几何层」的关键一步。

抽取的确定性事实：
  · 图层表
  · 模型空间实体计数（按类型）
  · 包围盒（$EXTMIN/$EXTMAX，及实体累加 extents）
  · 单位（$INSUNITS）
  · 尺寸标注（DIMENSION）的测量值与文本 —— 对应图纸上的 3 / 3.5 / 6 / 8 / 2
  · 文本实体（TEXT/MTEXT）内容 —— 图上 R12 / 2xØ5.6 这类标注

「正向对照」用途：拿上游 gold.dwg 跑本探针，得到的就是**正确答案的几何指纹**；
被测系统产出同格式文件后跑同一探针，逐项对比即可。

用法：
    python tools/probe_dwg_geometry.py --dwg <file.dwg> [--libredwg DIR] [--json-out FILE]
"""

from __future__ import annotations

import argparse
import collections
import json
import os
import shutil
import subprocess
import sys
import tempfile

try:
    import ezdxf
    from ezdxf import bbox as ezbbox   # 必须显式导入：ezdxf.bbox 不会自动加载
except ImportError:
    sys.exit("需要 ezdxf：pip install ezdxf")


def find_libredwg(explicit: str | None) -> str | None:
    """定位 dwg2dxf。顺序：显式参数 → 常见本地目录 → PATH。"""
    names = ["dwg2dxf.exe", "dwg2dxf"]
    if explicit:
        for n in names:
            p = os.path.join(explicit, n)
            if os.path.exists(p):
                return p
    here = os.path.dirname(os.path.abspath(__file__))
    cands = [
        os.path.join(here, "libredwg"),
        os.path.join(os.path.dirname(here), "tools", "libredwg"),
        r"C:\cad_repro\tools\libredwg",
    ]
    for d in cands:
        for n in names:
            p = os.path.join(d, n)
            if os.path.exists(p):
                return p
    for n in names:
        p = shutil.which(n)
        if p:
            return p
    return None


def dwg_to_dxf(dwg2dxf: str, dwg: str, out_dir: str) -> str:
    dxf = os.path.join(out_dir, os.path.splitext(os.path.basename(dwg))[0] + ".dxf")
    r = subprocess.run([dwg2dxf, "-o", dxf, dwg],
                       capture_output=True, encoding="utf-8", errors="replace")
    if not os.path.exists(dxf):
        raise RuntimeError(f"dwg2dxf 未产出文件。stderr:\n{(r.stderr or '')[:600]}")
    return dxf


def probe(dxf_path: str) -> dict:
    doc = ezdxf.readfile(dxf_path)
    msp = doc.modelspace()

    by_type = collections.Counter()
    by_layer = collections.Counter()
    for e in msp:
        by_type[e.dxftype()] += 1
        try:
            by_layer[e.dxf.layer] += 1
        except Exception:  # noqa: BLE001
            pass

    # 尺寸标注：取测量值与文本（图上 3 / 3.5 / 6 / 8 / 2 应出现在这里）
    dims = []
    for e in msp:
        if e.dxftype() != "DIMENSION":
            continue
        item = {"dimtype": int(getattr(e.dxf, "dimtype", -1))}
        try:
            item["measurement"] = round(float(e.get_measurement()), 4)
        except Exception:
            item["measurement"] = None
        try:
            item["text"] = e.dxf.text
        except Exception:
            item["text"] = None
        try:
            item["layer"] = e.dxf.layer
        except Exception:
            item["layer"] = None
        dims.append(item)

    # 文本实体
    texts = []
    for e in msp:
        if e.dxftype() in ("TEXT", "MTEXT"):
            try:
                texts.append(e.dxf.text if e.dxftype() == "TEXT" else e.text)
            except Exception:
                pass

    # 包围盒：优先用 header，退化为实体累加
    ext = ezbbox.extents(msp)
    bbox = None
    if ext.has_data:
        bbox = [round(ext.extmin.x, 4), round(ext.extmin.y, 4),
                round(ext.extmax.x, 4), round(ext.extmax.y, 4)]
    hdr_bbox = None
    try:
        emin, emax = doc.header.get("$EXTMIN"), doc.header.get("$EXTMAX")
        if emin is not None and emax is not None:
            hdr_bbox = [round(float(emin[0]), 4), round(float(emin[1]), 4),
                        round(float(emax[0]), 4), round(float(emax[1]), 4)]
    except Exception:
        pass

    return {
        "dxf_version": doc.dxfversion,
        "insunits": doc.header.get("$INSUNITS"),
        "layers": sorted(l.dxf.name for l in doc.layers),
        "modelspace_entity_count": len(msp),
        "entities_by_type": dict(by_type.most_common()),
        "entities_by_layer": dict(by_layer.most_common()),
        "block_definitions": len(list(doc.blocks)),
        "dimensions": dims,
        "dimension_count": len(dims),
        "dimension_measurements": sorted(
            d["measurement"] for d in dims if d["measurement"] is not None),
        "texts": texts,
        "bbox_extents": bbox,
        "bbox_header": hdr_bbox,
        "bbox_size": ([round(bbox[2] - bbox[0], 4), round(bbox[3] - bbox[1], 4)]
                      if bbox else None),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dwg", required=True)
    ap.add_argument("--libredwg", default=None, help="含 dwg2dxf 的目录")
    ap.add_argument("--json-out", default=None)
    ap.add_argument("--keep-dxf", default=None, help="保留中间 DXF 到该路径")
    args = ap.parse_args()

    if not os.path.exists(args.dwg):
        sys.exit(f"找不到 {args.dwg}")

    dwg2dxf = find_libredwg(args.libredwg)
    if not dwg2dxf:
        sys.exit("找不到 dwg2dxf。下载 LibreDWG 预编译包并解压到 tools/libredwg/：\n"
                 "  https://github.com/LibreDWG/libredwg/releases\n"
                 "或用 --libredwg 指定目录。")

    print("=" * 76)
    print(f"几何探针: {os.path.basename(args.dwg)}  ({os.path.getsize(args.dwg)} B)")
    print(f"  转换器: {dwg2dxf}")
    print("=" * 76)

    tmp = tempfile.mkdtemp(prefix="dwgdump_")
    try:
        dxf = dwg_to_dxf(dwg2dxf, args.dwg, tmp)
        print(f"  DXF 中间产物: {os.path.getsize(dxf)/1024:.1f} KB")
        if args.keep_dxf:
            shutil.copy(dxf, args.keep_dxf)
            print(f"  已保留到: {args.keep_dxf}")

        r = probe(dxf)
    finally:
        if not args.keep_dxf:
            shutil.rmtree(tmp, ignore_errors=True)

    print(f"\n  DXF 版本  : {r['dxf_version']}")
    print(f"  单位      : $INSUNITS = {r['insunits']}")
    print(f"  图层({len(r['layers'])}) : {r['layers']}")
    print(f"  模型空间实体: {r['modelspace_entity_count']}")
    print(f"  实体类型  : {r['entities_by_type']}")
    print(f"  图层分布  : {r['entities_by_layer']}")
    print(f"  块定义    : {r['block_definitions']}")
    print(f"  包围盒    : 累加={r['bbox_extents']}  header={r['bbox_header']}")
    print(f"  尺寸      : {r['bbox_size']}")
    print(f"\n  尺寸标注 {r['dimension_count']} 个，测量值: {r['dimension_measurements']}")
    for d in r["dimensions"][:14]:
        print(f"     type={d['dimtype']:<5} measurement={d['measurement']:<10} "
              f"text={d['text']!r} layer={d['layer']!r}")
    if r["texts"]:
        print(f"\n  文本实体 {len(r['texts'])} 个: {r['texts'][:12]}")

    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as f:
            json.dump(r, f, ensure_ascii=False, indent=2)
        print(f"\n  指纹已写出: {args.json_out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
