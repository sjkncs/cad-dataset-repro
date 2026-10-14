#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
repro_handle_leak.py — 实证 VideoCAD 的 pickle 句柄泄漏（跨平台，缩小规模）

不必跑几小时训练：直接测量**进程打开句柄数**随取样本次数的增长。
泄漏写法线性增长 → 迟早撞上限；with 写法持平。

- Windows: ctypes -> GetProcessHandleCount
- Linux/macOS: len(os.listdir('/proc/self/fd')) 或 resource.getrlimit

用法：
    python tools/repro_handle_leak.py            # 默认 3000 次
    python tools/repro_handle_leak.py --n 5000
"""

from __future__ import annotations

import argparse
import os
import pickle
import shutil
import sys
import tempfile


def open_handle_count():
    """返回当前进程的打开句柄数；不支持则返回 None。"""
    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes
            k32 = ctypes.WinDLL("kernel32", use_last_error=True)
            k32.GetCurrentProcess.restype = wintypes.HANDLE
            n = wintypes.DWORD(0)
            ok = k32.GetProcessHandleCount(k32.GetCurrentProcess(), ctypes.byref(n))
            return n.value if ok else None
        except Exception:
            return None
    # POSIX
    try:
        return len(os.listdir("/proc/self/fd"))
    except Exception:
        pass
    try:
        import resource
        return resource.getrlimit(resource.RLIMIT_NOFILE)[0]
    except Exception:
        return None


def fd_limit():
    if sys.platform == "win32":
        try:
            import ctypes
            k32 = ctypes.WinDLL("kernel32")
            return k32._getmaxstdio()   # CRT 层 fd 上限（默认 512）
        except Exception:
            return None
    try:
        import resource
        return resource.getrlimit(resource.RLIMIT_NOFILE)[0]
    except Exception:
        return None


def make_pkl(path, n=8):
    with open(path, "wb") as f:
        pickle.dump({"frames": [b"\x00" * 16] * n, "actions": [], "timesteps": []}, f)


def leaky(path):
    """照抄 VideoCAD data_loader/sequence_retriver.py:29 的写法。"""
    data = pickle.load(open(path, "rb"))
    return data


def safe(path):
    with open(path, "rb") as fh:
        return pickle.load(fh)


def run(mode, path, n):
    err = None
    done = 0
    for i in range(1, n + 1):
        try:
            leaky(path) if mode == "leaky" else safe(path)
            done = i
        except OSError as e:
            err = e
            break
    return err, done


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=3000)
    args = ap.parse_args()

    print("=" * 74)
    print("VideoCAD pickle 句柄泄漏实证")
    print(f"  平台 {sys.platform}   fd 上限(CRT/rlimit) = {fd_limit()}")
    print("=" * 74)

    tmp = tempfile.mkdtemp(prefix="vclk_")
    try:
        p = os.path.join(tmp, "sample_data.pkl")
        make_pkl(p)

        for mode, label in (("leaky", "泄漏写法  pickle.load(open(...))  ← 上游原写法"),
                            ("safe", "正确写法  with open(...) as fh")):
            base = open_handle_count()
            err, done = run(mode, p, args.n)
            peak = open_handle_count()
            print(f"\n[{label}]")
            print(f"  起始句柄 {base}   →   结束句柄 {peak}   "
                  f"（{'增长 ' + str(peak - base) if base is not None and peak is not None else 'n/a'}）")
            if err is None:
                print(f"  {done} 次调用全部成功")
            else:
                print(f"  ❌ 第 {done} 次失败: {type(err).__name__}: {err}")

        print("\n" + "=" * 74)
        print("说明：泄漏写法每次调用多留一个句柄，线性增长，")
        print("      最终会在进程/CRT 句柄上限处失败；with 写法持平。")
        print("      训练场景每 epoch 调用 N 次（N=样本数），故必然累积。")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
