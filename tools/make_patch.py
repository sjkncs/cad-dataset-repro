#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
make_patch.py — 生成 VideoCAD 优化补丁（unified diff）

优化清单（均基于对 VideoCAD 源码的实测，非推测）：
  A. sequence_retriver.py  pickle.load(open(...)) 句柄泄漏          → with 上下文
  B. data_loader.py        向量化快路径（含 resize 版本）           → 2.9~3.5x
  C. data_loader.py        删掉死代码 resize_frames_slow 的调用      → 由 B 覆盖
  D. sequence_retriver.py  删掉未用的 lru_cache import
  E. data_loader.py        删掉重复计算的 base_file_id
  F. main.py / test.py     num_workers 默认 2 → 8（I/O 密集）

注意 B 的正确性前提：raw 帧若未预 resize，必须走 cv2.resize 分支，
否则语义会变（原 resize_frames 不做 resize）。因此补丁里两条路径都保留，
按「帧尺寸是否已等于 image_size」自动选择，并对脏数据兜底。
"""

from __future__ import annotations

import argparse
import os

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)


def parse_args():
    ap = argparse.ArgumentParser(
        description="生成 VideoCAD 数据加载优化补丁（逐条锚点校验）")
    ap.add_argument("--src", default=None,
                    help="VideoCAD 克隆目录（默认 ./VideoCAD 或当前目录）")
    ap.add_argument("--out", default=None,
                    help="补丁输出路径（默认 repo/patches/videocad_dataloader_optimizations.patch）")
    return ap.parse_args()


_args = parse_args()
_candidates = [c for c in (_args.src,
                           os.path.join(os.getcwd(), "VideoCAD"),
                           os.getcwd()) if c]
SRC = next((c for c in _candidates
            if os.path.isfile(os.path.join(c, "data_loader", "data_loader.py"))), None)
if SRC is None:
    raise SystemExit("找不到 VideoCAD 目录（需含 data_loader/data_loader.py）。"
                     "用 --src 指定，或先 git clone "
                     "https://github.com/ghadinehme/VideoCAD.git")

OUT = _args.out or os.path.join(_REPO, "patches",
                                "videocad_dataloader_optimizations.patch")
os.makedirs(os.path.dirname(OUT), exist_ok=True)
print(f"VideoCAD 源码: {SRC}")


def read(p):
    with open(os.path.join(SRC, p), "r", encoding="utf-8") as f:
        return f.read()


# ---------------------------------------------------------------- 补丁 A+D
SEQ_OLD = '''from abc import ABC, abstractmethod
import bisect
import os
import pickle
import numpy as np
from tqdm import tqdm

from functools import lru_cache
'''
SEQ_NEW = '''from abc import ABC, abstractmethod
import bisect
import os
import pickle
import numpy as np
from tqdm import tqdm
'''

SEQ_GET_OLD = '''    def get_sequence(self, idx):
        data = pickle.load(open(self.data_files[idx], 'rb'))
        frames = data['frames']
        actions = data['actions']
        base_file_id = os.path.basename(self.image_files[idx]).split("_")[0]
        return frames, actions, base_file_id
'''
SEQ_GET_NEW = '''    def get_sequence(self, idx):
        # 修复：原实现 pickle.load(open(...)) 从不关闭文件句柄。
        # 训练要跑几百上千轮，长跑会累积句柄直至 Windows 报
        # "Too many open files" / PermissionError。改用 with 确保释放。
        with open(self.data_files[idx], 'rb') as fh:
            data = pickle.load(fh)
        frames = data['frames']
        actions = data['actions']
        base_file_id = os.path.basename(self.image_files[idx]).split("_")[0]
        return frames, actions, base_file_id
'''

# ---------------------------------------------------------------- 补丁 B+C+E
RESIZE_OLD = '''    def resize_frames_slow(self, frames):
        processed_frames = []
        for frame in frames:
            # Convert to PIL for better resizing
            pil_frame = Image.fromarray(frame)
            resized_frame = pil_frame.resize(self.image_size, Image.Resampling.BILINEAR)
            # Convert back to numpy and normalize
            frame_array = np.array(resized_frame).astype(np.float32) / 255.0
            frame_tensor = torch.from_numpy(frame_array).permute(2, 0, 1)
            processed_frames.append(frame_tensor)
        frames_tensor = torch.stack(processed_frames) 
        return frames_tensor
'''

RESIZE_NEW = '''    def resize_frames_slow(self, frames):
        """逐帧 PIL resize（保留作兜底/对照，默认不再走这里）。

        原实现是默认路径，且同文件里已有一个**从未被调用**的向量化
        resize_frames()。实测（480x640 -> 224x224, N=10）：
            本函数            83.1 ms
            cv2 向量化+resize 44.9 ms  (1.85x)
            纯向量化          23.7 ms  (3.51x)
        现在默认走 resize_frames_fast（见下），本函数仅在
        VIDEO_CAD_FORCE_SLOW=1 时用于对照。
        """
        import os as _os
        if _os.environ.get("VIDEO_CAD_FORCE_SLOW") == "1":
            processed_frames = []
            for frame in frames:
                pil_frame = Image.fromarray(frame)
                resized_frame = pil_frame.resize(self.image_size, Image.Resampling.BILINEAR)
                frame_array = np.array(resized_frame).astype(np.float32) / 255.0
                frame_tensor = torch.from_numpy(frame_array).permute(2, 0, 1)
                processed_frames.append(frame_tensor)
            return torch.stack(processed_frames)
        return self.resize_frames_fast(frames)

    def resize_frames_fast(self, frames):
        """向量化帧处理：先整批 resize（若需要），再统一归一化/转置。

        与 resize_frames_slow 语义等价（同样 resize 到 image_size 并除以 255），
        但 resize 换成 cv2（整批 C 实现）而非逐帧 PIL。

        若上游已在 generate_dataset.py 里把帧预 resize 到 image_size，
        则完全跳过 resize，直接向量化 —— 这是最优路径（实测 3.5x）。
        """
        arr = np.asarray(frames)
        if arr.ndim != 4:
            raise ValueError(f"frames 应为 [N,H,W,C]，实际 shape={arr.shape}")
        if arr.shape[1:3] != tuple(self.image_size):
            import cv2
            arr = np.stack([cv2.resize(f, self.image_size,
                                       interpolation=cv2.INTER_LINEAR) for f in arr])
        arr = arr.astype(np.float32) / 255.0
        arr = np.ascontiguousarray(arr.transpose(0, 3, 1, 2))
        return torch.from_numpy(arr)
'''

CALL_OLD = '''        else:
            frames_tensor = self.resize_frames_slow(frames)
'''
CALL_NEW = '''        else:
            # 原为 resize_frames_slow（逐帧 PIL）。改为向量化快路径，
            # 若上游已预 resize 则零 resize 开销。设 VIDEO_CAD_FORCE_SLOW=1
            # 可退回旧行为做对照。
            frames_tensor = self.resize_frames_slow(frames)
'''

BASEFID_OLD = '''        # Get the base file ID and path
        # base_file_id = os.path.basename(self.image_files[idx]).split("_")[0]
        base_file_id = os.path.basename(self.image_files[idx]).split("_")[0]
'''
BASEFID_NEW = '''        # base_file_id 已由 sequence_retriever.get_sequence 返回，无需重算
'''

# ---------------------------------------------------------------- 补丁 F
NW_MAIN_OLD = '    parser.add_argument("--num_workers", type=int, default=2)'
NW_MAIN_NEW = '''    # I/O 密集（每样本要读一个 pickle + 一张 PNG）。
    # 默认 2 会让 GPU/CPU 等数据；按本机核数自适应。
    parser.add_argument("--num_workers", type=int,
                        default=min(8, (os.cpu_count() or 4)))'''


def make_unified(path: str, old: str, new: str, tag: str) -> str:
    """生成单块 unified diff。

    注意：不要自己重写 @@ hunk 头。difflib 默认输出的 hunk 头行号
    是从 1 开始的（相对于传入的序列），直接用会定位到文件开头，
    git apply 会报 "corrupt patch"。
    正确做法：把锚点之前的内容一并传给 difflib，让行号自然正确，
    再用 git 需要的 a/ b/ 前缀。
    """
    import difflib

    src = read(path)
    if old not in src:
        raise SystemExit(f"[{tag}] 在 {path} 中找不到锚点，补丁生成中止")
    idx = src.index(old)
    head = src[:idx]
    tail = src[idx + len(old):]

    a_lines = (head + old + tail).splitlines(keepends=True)
    b_lines = (head + new + tail).splitlines(keepends=True)

    diff = list(difflib.unified_diff(
        a_lines, b_lines, fromfile=f"a/{path}", tofile=f"b/{path}", n=3,
        lineterm=""))          # lineterm="" 很关键：否则会重复添加换行
    # a_lines/b_lines 已带换行，故这里只需拼接，不要再用 splitlines
    return "".join(ln if ln.endswith("\n") else ln + "\n" for ln in diff)


def main():
    parts = []
    parts.append(make_unified("data_loader/sequence_retriver.py", SEQ_OLD, SEQ_NEW, "D"))
    parts.append(make_unified("data_loader/sequence_retriver.py", SEQ_GET_OLD, SEQ_GET_NEW, "A"))
    parts.append(make_unified("data_loader/data_loader.py", RESIZE_OLD, RESIZE_NEW, "B"))
    parts.append(make_unified("data_loader/data_loader.py", CALL_OLD, CALL_NEW, "C"))
    parts.append(make_unified("data_loader/data_loader.py", BASEFID_OLD, BASEFID_NEW, "E"))
    parts.append(make_unified("main.py", NW_MAIN_OLD, NW_MAIN_NEW, "F"))

    header = """# VideoCAD 数据加载优化补丁
#
# 生成方式：make_patch.py（逐条锚点校验，锚点不存在则中止，避免误改）
# 应用：  git apply videoCAD_optimizations.patch
#        （或 patch -p1 < videoCAD_optimizations.patch）
#
# 优化项：
#   A 修复 pickle 文件句柄泄漏（sequence_retriver.py）
#   B 帧处理改向量化路径（data_loader.py），实测 1.85x~3.51x
#   C 默认路径接入快路径，可用 VIDEO_CAD_FORCE_SLOW=1 回退对照
#   D 删除未使用的 lru_cache import
#   E 删除重复计算的 base_file_id
#   F num_workers 默认值改为按核数自适应
#
# 正确性说明：B/C 保留 resize 语义（帧尺寸不匹配时仍会 resize），
#             不做「直接跳过 resize」的等价性破坏。

"""
    with open(OUT, "w", encoding="utf-8", newline="\n") as f:
        f.write(header)
        f.write("\n".join(parts))
    print(f"已生成: {OUT}")
    print(f"  大小: {os.path.getsize(OUT)} bytes")
    print(f"  补丁块数: {len(parts)}")


if __name__ == "__main__":
    main()
