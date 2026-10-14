#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fetch_libredwg.py — 获取 LibreDWG 预编译包（DWG→DXF 转换用）

为什么需要它：
  DWG 是封闭二进制格式，ezdxf 读不了。
  `ezdxf.addons.odafc` 需要 ODA File Converter（需注册下载）。
  LibreDWG 是 **GPL 开源、免注册、官方提供 Windows 预编译包** 的替代方案，
  其 `dwg2dxf` 可把 DWG 转成 DXF，之后交给 ezdxf 做几何探针。

不把二进制提交进仓库（11.5 MB、GPL 三方件）——用本脚本按需下载到
tools/libredwg/（已在 .gitignore 中忽略）。

用法：
    python tools/fetch_libredwg.py                 # 默认 0.14 win64
    python tools/fetch_libredwg.py --version 0.14 --platform win64
"""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEST = os.path.join(ROOT, "tools", "libredwg")
BASE = "https://github.com/LibreDWG/libredwg/releases/download"

# 留档：本仓库实测通过的版本及其校验值（下载后可自行比对）
KNOWN_SHA256 = {
    "0.14/win64": "1ad7e15344d20b3426c3435b078d82fb84b35062815946b2cca9c5fc9810fea8",
}


def download(url: str, dest: str, tries: int = 4) -> None:
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "cad-repro/1.0"})
            with urllib.request.urlopen(req, timeout=300) as r, open(dest, "wb") as f:
                shutil.copyfileobj(r, f)
            if os.path.getsize(dest) > 1_000_000:
                return
            last = RuntimeError(f"仅 {os.path.getsize(dest)} 字节")
        except Exception as e:  # noqa: BLE001
            last = e
        if i < tries - 1:
            import time
            time.sleep(2 * (i + 1))
    raise RuntimeError(f"下载失败: {last}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", default="0.14")
    ap.add_argument("--platform", default="win64", choices=["win64", "win32"])
    ap.add_argument("--dest", default=DEST)
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    name = f"libredwg-{args.version}-{args.platform}.zip"
    url = f"{BASE}/{args.version}/{name}"
    os.makedirs(args.dest, exist_ok=True)
    target = os.path.join(args.dest, "dwg2dxf.exe" if "win" in args.platform else "dwg2dxf")

    if os.path.exists(target) and not args.force:
        print(f"已存在: {target}（用 --force 重新下载）")
        return 0

    print("=" * 74)
    print(f"下载 LibreDWG {args.version} / {args.platform}")
    print(f"  {url}")
    print("=" * 74)

    tmp = tempfile.mkdtemp(prefix="libredwg_")
    try:
        zpath = os.path.join(tmp, name)
        download(url, zpath)
        size = os.path.getsize(zpath)
        sha = hashlib.sha256(open(zpath, "rb").read()).hexdigest()
        print(f"  下载完成: {size/1024/1024:.2f} MB")
        print(f"  sha256  : {sha}")

        key = f"{args.version}/{args.platform}"
        if key in KNOWN_SHA256:
            exp = KNOWN_SHA256[key]
            print(f"  期望值  : {exp}")
            if sha.lower() == exp:
                print("  ✅ 与留档校验值一致")
            else:
                print("  ⚠️ 与留档值不一致 —— 上游可能重新打包，请自行判断")

        print("\n  解压…")
        with zipfile.ZipFile(zpath) as z:
            z.extractall(args.dest)

        # LibreDWG 的 zip 可能带一层目录，把可执行文件提到 dest 根下
        if not os.path.exists(target):
            for dirpath, _dirs, files in os.walk(args.dest):
                for f in files:
                    if f.lower() == os.path.basename(target).lower():
                        shutil.copy(os.path.join(dirpath, f), target)
                        break

        if not os.path.exists(target):
            print(f"\n  ⚠️ 解压后未找到 {os.path.basename(target)}，请手动检查 {args.dest}")
            return 1

        print(f"  ✅ 可用: {target}")

        # 自检：对 dwg2dxf --version
        try:
            r = subprocess.run([target, "--version"], capture_output=True,
                               encoding="utf-8", errors="replace", timeout=30)
            first = (r.stdout or r.stderr or "").strip().splitlines()
            if first:
                print(f"  版本输出: {first[0]}")
        except Exception as e:  # noqa: BLE001
            print(f"  版本自检跳过: {type(e).__name__}")

        print("\n  下一步：")
        print("    python tools/probe_dwg_geometry.py --dwg <file.dwg>")
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
