#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""probe_bench.py — 探测 autocad-bench 与其余 Markov 数据集的可用性/结构。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from hf_util import api_info, api_tree  # noqa: E402

for ds in ["markov-ai/autocad-bench-tasks", "markov-ai/autocad-bench",
           "markov-ai/computer-use-large", "markov-ai/apex-agents"]:
    print("=" * 70)
    print(ds)
    try:
        info = api_info(ds)
        print(f"  下载={info.get('downloads')}  赞={info.get('likes')}  "
              f"gated={info.get('gated')}  改={str(info.get('lastModified'))[:10]}")
        try:
            t = api_tree(ds, "main")
            for it in t[:12]:
                print(f"    {it.get('type','?'):<10} {it.get('path')}")
            if len(t) > 12:
                print(f"    ... 共 {len(t)} 项")
        except Exception as e:
            print(f"    列目录失败: {type(e).__name__}")
    except Exception as e:
        print(f"  不可用: {type(e).__name__}: {str(e)[:120]}")
