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
        gc_fail = None
        try:
            try:
                for i in range(1, 20001):
                    pickle.load(open(p, "rb"))
            except OSError as e:
                gc_fail = (i, e)
            if gc_fail:
                print(f"    20000 次: ❌ 第 {gc_fail[0]} 次失败 "
                      f"{type(gc_fail[1]).__name__}: {gc_fail[1]}")
            else:
                print("    20000 次: ✅ 全部成功（引用计数在表达式结束时即回收）")
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
        # 判定必须结合「是否真的累积到失败」，不能只看 ResourceWarning。
        # ResourceWarning 只说明"未显式关闭"，不等于"泄漏"——
        # CPython 的引用计数会在表达式结束时回收它。
        if gc_fail:
            print("  ❌ 即使 gc 关闭也累积到失败 → 这是**功能性 bug**，值得报上游。")
        elif res:
            print("  ⚠️ 检测到未显式关闭（ResourceWarning），但在 CPython 上")
            print("     引用计数会在表达式结束时立即回收，gc.disable() 下 20000 次也未失败。")
            print("  → **不是功能性 bug**，属代码卫生问题（with 更明确、消除告警）。")
            print("     不应作为 bug 报给上游；非引用计数实现（PyPy）下才可能累积，")
            print("     但本脚本未验证该情形，不作断言。")
        else:
            print("  ✅ 未检测到未关闭文件，无问题。")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
