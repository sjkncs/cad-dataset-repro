#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
create_issue.py — 通过 GitHub API 创建 issue（显式 UTF-8）

为什么不用 `gh issue create --body-file`：
  Windows 上 gh 读文件可能用系统默认编码（cp936），把 UTF-8 正文弄坏。
  与其赌，不如统一走 API 并显式 utf-8，和本仓库其余工具一致。

用法：
    python tools/create_issue.py --repo owner/name \
        --title-file title.txt --body-file body.md [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys


def gh(method: str, endpoint: str, payload: dict | None = None) -> dict:
    cmd = ["gh", "api", "-X", method, endpoint]
    if payload is not None:
        cmd += ["--input", "-"]
    p = subprocess.run(
        cmd,
        input=json.dumps(payload, ensure_ascii=False) if payload else None,
        capture_output=True, encoding="utf-8", errors="strict")
    if p.returncode != 0:
        raise RuntimeError(f"gh api {method} {endpoint} 失败:\n{(p.stderr or '')[:800]}")
    return json.loads(p.stdout) if (p.stdout or "").strip() else {}


def looks_mojibake(s: str) -> bool:
    return any(0xE000 <= ord(c) <= 0xF8FF for c in s)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--title-file", required=True)
    ap.add_argument("--body-file", required=True)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    with open(args.title_file, "r", encoding="utf-8") as f:
        title = f.read().strip()
    with open(args.body_file, "r", encoding="utf-8") as f:
        body = f.read()

    print(f"仓库 : {args.repo}")
    print(f"标题 : {title}")
    print(f"正文 : {len(body)} 字符, {body.count(chr(10))} 行")
    if looks_mojibake(title) or looks_mojibake(body):
        sys.exit("❌ 标题或正文含 PUA 字符，已写坏，中止")
    if not title or len(body) < 200:
        sys.exit("❌ 标题为空或正文过短，中止")

    if args.dry_run:
        print("\n[dry-run] 未提交。正文首 200 字：")
        print(body[:200])
        return 0

    # 提交前确认仓库存在且允许 issue
    repo = gh("GET", f"/repos/{args.repo}")
    if not repo.get("has_issues"):
        sys.exit(f"❌ {args.repo} 未启用 issue")
    print(f"目标仓库确认: {repo['full_name']}  has_issues={repo['has_issues']}")

    issue = gh("POST", f"/repos/{args.repo}/issues",
               {"title": title, "body": body})
    num = issue["number"]

    # 回读校验编码
    back = gh("GET", f"/repos/{args.repo}/issues/{num}")
    ok_title = back["title"] == title
    ok_body = back["body"].strip() == body.strip()
    print(f"\n创建成功: #{num}")
    print(f"  URL: {back['html_url']}")
    print(f"  标题回读: {'✅ 一致' if ok_title else '❌ 不一致'}")
    print(f"  正文回读: {'✅ 一致' if ok_body else '⚠️ 有差异（可能仅换行/尾空白）'}")
    if not ok_title:
        print(f"    期望: {title!r}")
        print(f"    实际: {back['title']!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
