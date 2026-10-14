#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
push_via_api.py — 当 git 的 HTTPS/SSH 推送不通时，用 GitHub Git Data API 提交

背景（本机网络实测）：
  · github.com:443          TCP = False（git push 走 HTTPS 必失败）
  · ssh.github.com:443      TCP = True，但本机 SSH key 是 **deploy key**，
                            只有 song-quiz 的写权限 → "denied to deploy key"
  · api.github.com（走 gh）  可用 ✅

因此改用 Git Data API 上传改动：blob -> tree -> commit -> update ref。
不修改历史，只是在当前 head 之上追加一个提交。

用法：
  python push_via_api.py --repo sjkncs/cad-dataset-repro --branch main \
      --message "commit msg" --file path/in/repo=local/path ...
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
    p = subprocess.run(cmd, input=json.dumps(payload) if payload else None,
                       capture_output=True, text=True, encoding="utf-8")
    if p.returncode != 0:
        raise RuntimeError(f"gh api {method} {endpoint} 失败:\n{p.stderr.strip()[:600]}")
    return json.loads(p.stdout) if p.stdout.strip() else {}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True, help="owner/name")
    ap.add_argument("--branch", default="main")
    ap.add_argument("--message", required=True)
    ap.add_argument("--file", action="append", default=[],
                    help="仓库内路径=本地路径（可重复）")
    ap.add_argument("--delete", action="append", default=[],
                    help="要删除的仓库内路径（可重复）")
    args = ap.parse_args()

    if not args.file and not args.delete:
        sys.exit("没有要提交的文件")

    print(f"仓库: {args.repo}  分支: {args.branch}")

    # 1) 当前 head
    ref = gh("GET", f"/repos/{args.repo}/git/ref/heads/{args.branch}")
    head = ref["object"]["sha"]
    print(f"  当前 head: {head[:7]}")

    commit = gh("GET", f"/repos/{args.repo}/git/commits/{head}")
    base_tree = commit["tree"]["sha"]
    print(f"  当前 tree: {base_tree[:7]}")

    # 2) 为每个文件建 blob
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
        print(f"  blob {repo_path}  {len(content)} B  -> {blob['sha'][:7]}")
        tree_items.append({"path": repo_path, "mode": "100644",
                           "type": "blob", "sha": blob["sha"]})

    # 3) 删除项：sha=null 即从 tree 移除
    for repo_path in args.delete:
        print(f"  delete {repo_path}")
        tree_items.append({"path": repo_path, "mode": "100644",
                           "type": "blob", "sha": None})

    # 4) 新 tree
    tree = gh("POST", f"/repos/{args.repo}/git/trees",
              {"base_tree": base_tree, "tree": tree_items})
    print(f"  新 tree: {tree['sha'][:7]}")

    # 5) 新 commit
    new_commit = gh("POST", f"/repos/{args.repo}/git/commits", {
        "message": args.message,
        "tree": tree["sha"],
        "parents": [head],
    })
    print(f"  新 commit: {new_commit['sha'][:7]}")

    # 6) 更新分支引用
    gh("PATCH", f"/repos/{args.repo}/git/refs/heads/{args.branch}",
       {"sha": new_commit["sha"], "force": False})
    print(f"\n✅ 已提交并更新 {args.branch} -> {new_commit['sha'][:7]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
