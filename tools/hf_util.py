#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
hf_util.py — HuggingFace 访问工具（镜像优先 + 重试退避）

⚠️ 本机网络实测（重要）：
  · `huggingface.co`          DNS 被污染到 108.160.166.137（Dropbox 段），TCP 443 = False
  · `cdn-lfs.huggingface.co`  解析到 199.59.150.49（Twitter 段），TCP 443 = False
  · `hf-mirror.com`           TCP 443 = True，API 与文件下载均 HTTP 200 ✅

  所以默认走 **hf-mirror.com**。设环境变量 HF_ENDPOINT 可覆盖。
  这解释了此前随机出现的 URLError —— 直连是间歇性可通的。
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request

ENDPOINTS = [
    os.environ.get("HF_ENDPOINT", "").rstrip("/"),
    "https://hf-mirror.com",
    "https://huggingface.co",
]
ENDPOINTS = [e for e in ENDPOINTS if e]
UA = "cad-repro/1.0"


def _open(url: str, timeout: int, tries: int, backoff: float) -> bytes:
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                raise
            last = e
        except Exception as e:  # noqa: BLE001
            last = e
        if i < tries - 1:
            time.sleep(backoff * (2 ** i))
    raise last if last else RuntimeError("unknown")


def _try_all(path: str, timeout: int, tries: int, backoff: float) -> bytes:
    """依次尝试各 endpoint，任一成功即返回。"""
    errors = []
    for base in ENDPOINTS:
        url = f"{base}{path}"
        try:
            return _open(url, timeout, tries, backoff)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                raise
            errors.append(f"{base}: HTTP {e.code}")
        except Exception as e:  # noqa: BLE001
            errors.append(f"{base}: {type(e).__name__}")
    raise RuntimeError("所有 endpoint 均失败 -> " + " | ".join(errors))


def api_tree(dataset: str, path: str, tries: int = 4, timeout: int = 45) -> list[dict]:
    """列目录。"""
    data = _try_all(f"/api/datasets/{dataset}/tree/{path}", timeout, tries, 1.5)
    return json.loads(data.decode("utf-8"))


def api_info(dataset: str, tries: int = 4, timeout: int = 45) -> dict:
    data = _try_all(f"/api/datasets/{dataset}", timeout, tries, 1.5)
    return json.loads(data.decode("utf-8"))


def fetch_bytes(dataset: str, remote: str, tries: int = 4, timeout: int = 300,
                max_bytes: int | None = None) -> bytes | None:
    """下载文件内容；超出 max_bytes 返回 None。"""
    data = _try_all(f"/datasets/{dataset}/resolve/main/{remote}", timeout, tries, 2.0)
    if max_bytes is not None and len(data) > max_bytes:
        return None
    return data


if __name__ == "__main__":
    print("endpoints:", ENDPOINTS)
    for base in ENDPOINTS:
        host = base.split("//")[-1]
        print(f"  {host}")
    print()
    try:
        t = api_tree("markov-ai/cad-1000-hours", "main/sketchup")
        print(f"✅ API 可用，sketchup 分组 {len(t)} 个任务")
    except Exception as e:  # noqa: BLE001
        print(f"❌ API 失败: {e}")
