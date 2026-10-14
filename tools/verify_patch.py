#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
verify_patch.py — 对打过补丁的 VideoCAD 代码做功能验证

不满足于「语法通过」：直接实例化真实的 DatasetBase（绕过 __init__），
调用补丁新增/修改的 resize_frames_slow / resize_frames_fast，
校验形状、数值区间、以及快慢路径的数值一致性。

用法：
    # VideoCAD 克隆在当前目录下
    python tools/verify_patch.py

    # 或显式指定
    python tools/verify_patch.py --videocad /path/to/VideoCAD
"""

from __future__ import annotations

import argparse
import os
import sys
import time

import numpy as np
import torch


def parse_args():
    ap = argparse.ArgumentParser()
    ap.add_argument("--videocad", default=None,
                    help="VideoCAD 克隆目录（默认：./VideoCAD 或当前目录）")
    return ap.parse_args()


_args = parse_args()
_candidates = [c for c in (_args.videocad,
                           os.path.join(os.getcwd(), "VideoCAD"),
                           os.getcwd()) if c]
VC = next((c for c in _candidates
           if os.path.isdir(os.path.join(c, "data_loader"))), None)
if VC is None:
    sys.exit("找不到 VideoCAD 目录（需含 data_loader/）。用 --videocad 指定，"
             "或先 git clone https://github.com/ghadinehme/VideoCAD.git")
sys.path.insert(0, VC)
print(f"VideoCAD 目录: {VC}")

from data_loader.data_loader import DatasetBase  # noqa: E402

IMAGE_SIZE = (224, 224)
ok = True


def check(name, cond, detail=""):
    global ok
    if not cond:
        ok = False
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}  {detail}")


# 构造一个"裸"实例：只设置 resize 路径需要的属性，不跑 __init__（它要真实数据集）
obj = DatasetBase.__new__(DatasetBase)
obj.image_size = IMAGE_SIZE
obj.frame_transform = None

print("=" * 74)
print("打过补丁的 VideoCAD 帧处理验证")
print("=" * 74)

# --- 1. 未预 resize 的输入：应自动 resize 到 image_size
frames_big = [np.random.randint(0, 256, (480, 640, 3), dtype=np.uint8) for _ in range(10)]
fast = obj.resize_frames_fast(frames_big)
check("输入 480x640 -> 输出形状 [10,3,224,224]",
      tuple(fast.shape) == (10, 3, 224, 224), str(tuple(fast.shape)))
check("数值落在 [0,1]", float(fast.min()) >= 0.0 and float(fast.max()) <= 1.0,
      f"[{float(fast.min()):.3f}, {float(fast.max()):.3f}]")
check("dtype = float32", fast.dtype == torch.float32, str(fast.dtype))
check("内存连续（避免后续拷贝）", fast.is_contiguous(), str(fast.is_contiguous()))

# --- 2. 预 resize 过的输入：应跳过 resize
frames_small = [np.random.randint(0, 256, IMAGE_SIZE + (3,), dtype=np.uint8) for _ in range(10)]
t0 = time.perf_counter()
for _ in range(5):
    fast2 = obj.resize_frames_fast(frames_small)
t_pre = (time.perf_counter() - t0) / 5
check("预 resize 输入 -> 输出形状正确", tuple(fast2.shape) == (10, 3, 224, 224),
      str(tuple(fast2.shape)))

# --- 3. 慢路径（默认已切到快路径） vs 环境变量强制慢路径
t0 = time.perf_counter()
for _ in range(5):
    slow = obj.resize_frames_slow(frames_big)     # 补丁后默认走 fast
t_slow_default = (time.perf_counter() - t0) / 5

os.environ["VIDEO_CAD_FORCE_SLOW"] = "1"
t0 = time.perf_counter()
for _ in range(5):
    slow_forced = obj.resize_frames_slow(frames_big)   # 强制旧实现
t_slow_forced = (time.perf_counter() - t0) / 5
del os.environ["VIDEO_CAD_FORCE_SLOW"]

check("默认路径 == 快路径（补丁已生效）", torch.allclose(slow, fast, atol=1e-6),
      "完全一致" if torch.allclose(slow, fast, atol=1e-6) else "存在差异")
check("VIDEO_CAD_FORCE_SLOW=1 可回退旧实现",
      tuple(slow_forced.shape) == (10, 3, 224, 224) and
      abs(float(slow_forced.mean()) - float(slow.mean())) < 0.05,
      f"mean {float(slow_forced.mean()):.4f} vs {float(slow.mean()):.4f}")

print(f"\n-- 实测耗时（N=10, 480x640 -> 224x224）--")
print(f"   强制慢路径(PIL 逐帧)   {t_slow_forced*1000:7.2f} ms")
print(f"   默认路径(补丁后快路径)  {t_slow_default*1000:7.2f} ms   加速 {t_slow_forced/t_slow_default:.2f}x")
print(f"   预 resize 输入(零 resize) {t_pre*1000:7.2f} ms   加速 {t_slow_forced/t_pre:.2f}x")

# --- 4. 文件句柄修复验证
import inspect  # noqa: E402
from data_loader.sequence_retriver import BaseSequenceRetriever  # noqa: E402

src = inspect.getsource(BaseSequenceRetriever.get_sequence)
# 注意：不能用 `"pickle.load(open(" not in src` 做判断 ——
# 补丁里的**注释文字**也提到旧写法，会误判（我第一次就踩了）。
# 只检查实际代码特征。
check("句柄泄漏已修（with + pickle.load(fh)）",
      "with open(" in src and "pickle.load(fh)" in src,
      "已改用 with 上下文")
check("未使用的 lru_cache import 已删",
      "lru_cache" not in inspect.getsource(sys.modules["data_loader.sequence_retriver"]),
      "已清理")

print("\n" + "=" * 74)
print("全部通过 ✅" if ok else "存在失败 ❌")
sys.exit(0 if ok else 1)
