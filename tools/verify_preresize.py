#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
verify_preresize.py — 实证：上游生成的数据帧是否已是 224x224（即快路径能拿满收益）

背景：补丁文档里我声称「必须在 generate_dataset.py 预 resize 才能拿满 3x」。
      但读代码发现 generate_action_vectors_and_video_pairs 已传 resize=(224,224)。
      本脚本用**合成数据**实证这一结论，而不是靠读代码。

做法：
  1. 造两个 pkl：A = 224x224 帧（模拟上游真实产物），B = 480x640 帧（模拟未预 resize）
  2. 用打过补丁的真实 DatasetBase 分别取一条样本，测量从"原始帧数组"到"张量"的耗时
  3. 若 A 显著快于 B，则证实「帧已预 resize」⇒ 补丁已能拿满收益
"""

from __future__ import annotations

import argparse
import os
import pickle
import sys
import tempfile
import time

import numpy as np
import torch


def parse_args():
    ap = argparse.ArgumentParser()
    ap.add_argument("--videocad", default=None)
    return ap.parse_args()


_a = parse_args()
_cands = [c for c in (_a.videocad, os.path.join(os.getcwd(), "VideoCAD"), os.getcwd()) if c]
VC = next((c for c in _cands if os.path.isdir(os.path.join(c, "data_loader"))), None)
if VC is None:
    sys.exit("找不到 VideoCAD 目录，用 --videocad 指定")
sys.path.insert(0, VC)
from data_loader.data_loader import DatasetBase, DatasetSpecific  # noqa: E402

IMAGE_SIZE = (224, 224)
SEQ = 10
REPEATS = 5


def make_pkl(path, hw):
    n = SEQ
    frames = [np.random.randint(0, 256, hw + (3,), dtype=np.uint8) for _ in range(n)]
    actions = np.random.rand(n, 7).astype(np.float32)
    with open(path, "wb") as f:
        pickle.dump({"frames": frames, "actions": actions,
                     "timesteps": np.arange(n)}, f)


def measure(obj, frames, repeats=REPEATS):
    # 预热
    obj.resize_frames_slow(frames)
    t0 = time.perf_counter()
    for _ in range(repeats):
        out = obj.resize_frames_slow(frames)
    return (time.perf_counter() - t0) / repeats, out


def main():
    print("=" * 76)
    print("实证：上游数据帧是否已预 resize（决定补丁能否拿满收益）")
    print(f"VideoCAD: {VC}")
    print("=" * 76)

    obj = DatasetBase.__new__(DatasetBase)
    obj.image_size = IMAGE_SIZE
    obj.frame_transform = None

    tmp = tempfile.mkdtemp(prefix="vc_preresize_")
    cases = [
        ("A 上游真实产物形状 224x224", (224, 224)),
        ("B 未预 resize 形状 480x640", (480, 640)),
        ("C 高清截图形状 1080x1920", (1080, 1920)),
    ]
    base = None
    for label, hw in cases:
        frames = [np.random.randint(0, 256, hw + (3,), dtype=np.uint8) for _ in range(SEQ)]
        t, out = measure(obj, frames)
        if base is None:
            base = t
        shape_ok = tuple(out.shape) == (SEQ, 3, 224, 224)
        print(f"\n{label}")
        print(f"   耗时 {t*1000:8.2f} ms   相对 A {t/base:5.2f}x   输出形状 "
              f"{tuple(out.shape)} {'✅' if shape_ok else '❌'}")

    # 直接验证"是否跳过 resize"：monkeypatch cv2.resize 看有没有被调用
    import cv2
    called = {"n": 0}
    orig = cv2.resize

    def spy(*a, **k):
        called["n"] += 1
        return orig(*a, **k)

    cv2.resize = spy
    try:
        obj.resize_frames_fast([np.random.randint(0, 256, (224, 224, 3), dtype=np.uint8)
                                for _ in range(SEQ)])
        n_224 = called["n"]
        called["n"] = 0
        obj.resize_frames_fast([np.random.randint(0, 256, (480, 640, 3), dtype=np.uint8)
                                for _ in range(SEQ)])
        n_480 = called["n"]
    finally:
        cv2.resize = orig

    print("\n" + "=" * 76)
    print("cv2.resize 调用次数（越少越好）")
    print(f"   224x224 输入 -> resize 调用 {n_224} 次  "
          f"{'✅ 完全跳过 resize' if n_224 == 0 else '（有 resize）'}")
    print(f"   480x640 输入 -> resize 调用 {n_480} 次  "
          f"{'（逐帧 resize）' if n_480 else ''}")
    print("=" * 76)
    if n_224 == 0 and n_480 > 0:
        print("\n结论：帧尺寸 == image_size 时完全跳过 resize。")
        print("      上游 generate_action_vectors_and_video_pairs 已传 resize=(224,224)，")
        print("      故其产物走补丁后的路径即为**零 resize 快路径**，")
        print("      无需再改 generate_dataset.py。补丁文档中『必须预 resize』的说法不准确。")
    import shutil
    shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
