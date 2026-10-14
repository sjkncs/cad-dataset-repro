#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
probe_leak_reality.py — 判定 pickle.load(open(...)) 在 CPython 上是否真泄漏

前提知识：
  CPython 用引用计数。`pickle.load(open(p,'rb'))` 里的文件对象是临时值，
  表达式结束即引用归零 → 立即被回收关闭。因此**在 CPython 上通常不泄漏**。
  而在 PyPy 等非引用计数实现上，要等 GC 才关，才可能累积。

本脚本用三种方式判定，而不是靠推断：
  1. 资源警告：开 -W error::ResourceWarning，临时对象不关会抛异常
  2. 强制延迟回收：gc.disable() + 累积大量未回收对象，看是否失败
  3. 显式保留引用（真正的泄漏写法）作为阳性对照
"""

from __future__ import annotations

import gc
import os
import pickle
import shutil
import sys
import tempfile
import warnings


def make_pkl(path):
    with open(path, "wb") as f:
        pickle.dump({"a": 1}, f)


def main():
    print("=" * 74)
    print("判定：pickle.load(open(...)) 在 CPython 上是否真泄漏")
    print(f"  实现 {sys.implementation.name} {sys.version.split()[0]}")
    print("=" * 74)

    tmp = tempfile.mkdtemp(prefix="leakchk_")
    try:
        p = os.path.join(tmp, "x.pkl")
        make_pkl(p)

        # ---- 测试 1：ResourceWarning 是否被触发
        print("\n[1] ResourceWarning 检测（临时文件对象若未关闭会告警）")
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            for _ in range(200):
                pickle.load(open(p, "rb"))
            gc.collect()
            res = [x for x in w if issubclass(x.category, ResourceWarning)]
        print(f"    200 次后 ResourceWarning 数: {len(res)}")
        print(f"    → {'⚠️ 有未关闭文件' if res else '✅ 无告警，说明临时对象已被回收关闭'}")

        # ---- 测试 2：gc 关闭时是否累积
        print("\n[2] gc.disable() 后反复调用（模拟延迟回收环境）")
        gc.disable()
        try:
            err = None
            try:
                for i in range(1, 20001):
                    pickle.load(open(p, "rb"))
            except OSError as e:
                err = (i, e)
            print(f"    20000 次: {'❌ 第 %d 次失败 %s: %s' % (err[0], type(err[1]).__name__, err[1]) if err else '✅ 全部成功'}")
        finally:
            gc.enable()

        # ---- 测试 3：阳性对照——真正持有引用不关闭
        print("\n[3] 阳性对照：真正持有引用不关闭（这才是真泄漏）")
        held = []
        err = None
        try:
            for i in range(1, 2001):
                held.append(open(p, "rb"))
        except OSError as e:
            err = (i, e)
        print(f"    持有 {len(held)} 个句柄: "
              f"{'❌ 第 %d 个失败 %s: %s' % (err[0], type(err[1]).__name__, err[1]) if err else '未触发上限'}")
        for f in held:
            f.close()

        print("\n" + "=" * 74)
        print("结论")
        print("=" * 74)
        if not res:
            print("  CPython 引用计数会在表达式结束时立即关闭临时文件，")
            print("  因此 `pickle.load(open(...))` 在 CPython 上**通常不构成句柄泄漏**。")
            print("  → 不应把它作为 bug 报给上游；最多作为代码风格建议（with 更明确），")
            print("    或在用非 CPython 实现（PyPy）时才是真问题。")
        else:
            print("  检测到未关闭文件，构成泄漏，值得报上游。")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
