#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
bench_resize.py — 量化 VideoCAD 数据加载中两条帧处理路径的性能差

背景（代码事实）：
  data_loader.py:379  resize_frames_slow()  ← data_loader.py:449 唯一调用点
  data_loader.py:368  resize_frames()       ← **全代码库从未被调用（死快路径）**

本脚本用真实形状（224x224、序列长度 10/20）对比两者，并做数值等价性校验。
"""
from __future__ import annotations

import time

import numpy as np
from PIL import Image

IMAGE_SIZE = (224, 224)
SEQ_LENS = (10, 20)
REPEATS = 5


def resize_frames_slow(frames, image_size=IMAGE_SIZE):
    """照抄 VideoCAD data_loader.py:379 的实现。"""
    processed = []
    for frame in frames:
        pil = Image.fromarray(frame)
        pil = pil.resize(image_size, Image.Resampling.BILINEAR)
        arr = np.array(pil).astype(np.float32) / 255.0
        processed.append(__import__("torch").from_numpy(arr).permute(2, 0, 1))
    return __import__("torch").stack(processed)


def resize_frames_fast(frames, image_size=IMAGE_SIZE):
    """照抄 VideoCAD data_loader.py:368 的实现（注意它不做 resize）。"""
    import torch
    f = frames.astype(np.float32) / 255.0
    f = np.stack(f)
    f = f.transpose(0, 3, 1, 2)
    return torch.from_numpy(f)


def main():
    import torch

    print("=" * 74)
    print("VideoCAD 帧处理路径基准测试")
    print(f"  image_size={IMAGE_SIZE}  repeats={REPEATS}")
    print("=" * 74)

    for n in SEQ_LENS:
        # 源帧用 480x640（接近 1080p 截图的常见缩放），强制走 resize
        frames = [np.random.randint(0, 256, (480, 640, 3), dtype=np.uint8) for _ in range(n)]

        # --- slow ---
        t0 = time.perf_counter()
        for _ in range(REPEATS):
            a = resize_frames_slow(frames)
        t_slow = (time.perf_counter() - t0) / REPEATS

        # --- fast（保留 resize，做法与 slow 等价但向量化）---
        import cv2

        def resize_frames_fast_resized(frames, image_size=IMAGE_SIZE):
            arr = np.stack(frames)                                   # [N,H,W,C] uint8
            arr = np.stack([cv2.resize(f, image_size,
                                       interpolation=cv2.INTER_LINEAR) for f in arr])
            arr = arr.astype(np.float32) / 255.0
            arr = arr.transpose(0, 3, 1, 2)
            return torch.from_numpy(np.ascontiguousarray(arr))

        t0 = time.perf_counter()
        for _ in range(REPEATS):
            b = resize_frames_fast_resized(frames)
        t_fast = (time.perf_counter() - t0) / REPEATS

        # --- 纯向量化（不 resize，即原 resize_frames 行为）---
        same_size = [np.random.randint(0, 256, IMAGE_SIZE + (3,), dtype=np.uint8) for _ in range(n)]
        t0 = time.perf_counter()
        for _ in range(REPEATS):
            c = resize_frames_fast(np.stack(same_size))
        t_vec = (time.perf_counter() - t0) / REPEATS

        print(f"\n序列长度 N={n}")
        print(f"  resize_frames_slow (现用)         {t_slow*1000:8.2f} ms")
        print(f"  cv2 向量化 + resize               {t_fast*1000:8.2f} ms   加速 {t_slow/t_fast:5.2f}x")
        print(f"  纯向量化(无 resize, 原快路径)      {t_vec*1000:8.2f} ms   加速 {t_slow/t_vec:5.2f}x")

        # 数值等价性：cv2 INTER_LINEAR vs PIL BILINEAR 应非常接近
        d = (a.numpy().astype(np.float64) - b.numpy().astype(np.float64))
        print(f"  数值一致性: max|Δ|={np.abs(d).max():.6f}  mean|Δ|={np.abs(d).mean():.8f}")


if __name__ == "__main__":
    main()
