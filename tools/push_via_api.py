#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
push_via_api.py — 当 git 的 HTTPS/SSH 推送不通时，用 GitHub Git Data API 提交

背景（本机网络实测）：
  · github.com:443          TCP = False（git push 走 HTTPS 必失败）
  · ssh.github.com:443      TCP = True，但本机 SSH key 是 **deploy key**，
                            只有本仓库之外的写权限 → "denied to deploy key"
  · api.github.com（走 gh）  可用 ✅

因此改用 Git Data API 上传改动：blob -> tree -> commit -> update ref。

⚠️ 编码纪律（血泪教训）：
  中文提交信息**绝不能**经 shell 命令行参数传给本脚本 —— PowerShell 的
  编码转换会把它变成私用区(PUA)乱码，而且**全程不报错**。
  必须写进 UTF-8 文件后由本脚本读取（--message-file）。
  所有 subprocess 调用显式 encoding='utf-8'，并在提交后**回读校验**，
  编码不对就中止且不更新 ref。

用法：
  python push_via_api.py --repo owner/name --branch main \
      --message-file msg.txt \
      --file path/in/repo=local/path ...
"""

from __future__ import annotations

import argparse
import base64
import json
import subprocess
import sys


def gh(method: str, endpoint: str, payload: dict | None = None) -> dict:
    cmd = ["gh", "api", "-X", method, endpoint]
    if payload is not None:
        cmd += ["--input", "-"]
    # 显式 utf-8：Windows 默认 cp936 会破坏中文。
    # 注意：指定 encoding 后 stdin 为文本模式，必须传 str（不能传 bytes）。
    # json.dumps 默认 ensure_ascii=True，非 ASCII 会转成 \uXXXX，因此这里最稳。
    p = subprocess.run(
        cmd,
        input=json.dumps(payload, ensure_ascii=False) if payload else None,
        capture_output=True, encoding="utf-8", errors="strict")
    if p.returncode != 0:
        raise RuntimeError(f"gh api {method} {endpoint} 失败:\n{(p.stderr or '')[:600]}")
    return json.loads(p.stdout) if (p.stdout or "").strip() else {}


def looks_mojibake(s: str) -> bool:
    """PUA（U+E000–U+F8FF）几乎总是编码损坏的产物。"""
    return any(0xE000 <= ord(c) <= 0xF8FF for c in s)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True, help="owner/name")
    ap.add_argument("--branch", default="main")
    ap.add_argument("--message-file", required=True,
                    help="UTF-8 编码的提交信息文件（不要用命令行传中文）")
    ap.add_argument("--file", action="append", default=[],
                    help="仓库内路径=本地路径（可重复）")
    ap.add_argument("--delete", action="append", default=[],
                    help="要删除的仓库内路径（可重复）")
    ap.add_argument("--force", action="store_true",
                    help="force 更新 ref（仅在确实要改写分支时使用）")
    args = ap.parse_args()

    if not args.file and not args.delete:
        sys.exit("没有要提交的文件")

    with open(args.message_file, "r", encoding="utf-8") as f:
        message = f.read()
    if not message.strip():
        sys.exit("提交信息为空")

    first_line = message.split("\n")[0]
    print(f"仓库: {args.repo}  分支: {args.branch}")
    print(f"提交信息首行: {first_line}")
    if looks_mojibake(message):
        sys.exit("❌ 提交信息含私用区(PUA)字符，文件本身已写坏。"
                 "请用 UTF-8 无 BOM 重新写出后重试。")

    # 1) 当前 head 与 tree
    ref = gh("GET", f"/repos/{args.repo}/git/ref/heads/{args.branch}")
    head = ref["object"]["sha"]
    commit = gh("GET", f"/repos/{args.repo}/git/commits/{head}")
    base_tree = commit["tree"]["sha"]
    print(f"  当前 head: {head[:7]}   tree: {base_tree[:7]}")

    # 2) blob
    tree_items = []
    for spec in args.file:
        if "=" not in spec:
            sys.exit(f"--file 需要 '仓库路径=本地路径' 形式，收到: {spec}")
        repo_path, local_path = spec.split("=", 1)
        with open(local_path, "rb") as f:
            content = f.read()
        blob = gh("POST", f"/repos/{args.repo}/git/blobs", {
            "content": base64.b64encode(content).decode("ascii"),
            "encoding": "base64",
        })
        print(f"  blob {repo_path}  {len(content)} B -> {blob['sha'][:7]}")
        tree_items.append({"path": repo_path, "mode": "100644",
                           "type": "blob", "sha": blob["sha"]})

    for repo_path in args.delete:
        print(f"  delete {repo_path}")
        tree_items.append({"path": repo_path, "mode": "100644",
                           "type": "blob", "sha": None})

    # 3) tree
    tree = gh("POST", f"/repos/{args.repo}/git/trees",
              {"base_tree": base_tree, "tree": tree_items})
    print(f"  新 tree: {tree['sha'][:7]}")

    # 4) commit
    new_commit = gh("POST", f"/repos/{args.repo}/git/commits", {
        "message": message, "tree": tree["sha"], "parents": [head],
    })
    sha = new_commit["sha"]
    print(f"  新 commit: {sha[:7]}")

    # 5) 回读校验（关键：确认编码没被破坏）
    back = gh("GET", f"/repos/{args.repo}/git/commits/{sha}")
    got_first = back["message"].split("\n")[0]
    if got_first != first_line:
        print("\n⚠️ 回读首行与预期不一致：")
        print(f"   写入: {first_line!r}")
        print(f"   回读: {got_first!r}")
        if looks_mojibake(got_first):
            sys.exit("❌ 编码被破坏（PUA 字符），已中止，ref 未更新")
        print("   （差异非 PUA，按换行处理差异继续）")
    else:
        print("  ✅ 编码回读校验通过")

    # 6) 更新 ref
    gh("PATCH", f"/repos/{args.repo}/git/refs/heads/{args.branch}",
       {"sha": sha, "force": bool(args.force)})
    print(f"\n✅ 已更新 {args.branch} -> {sha[:7]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
