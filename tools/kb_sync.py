#!/usr/bin/env python3
"""
kb_sync.py — 同步所有知识库仓库到本地,并重建全文索引。

核心通道:codeload.github.com(实测 17 MB/s)
禁止使用:Release 资产(19 KB/s)、raw.githubusercontent.com(被墙)、Git LFS

用法:
    python kb_sync.py                # 自动发现所有打了 hermes-kb topic 的仓库
    python kb_sync.py --repo a --repo b
    python kb_sync.py --list         # 只列出,不同步
    python kb_sync.py --no-index     # 只拉取,不重建索引
"""
import argparse
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
import time
import urllib.request

BASE = os.path.expanduser("~/.hermes/kb")
REPOS_DIR = os.path.join(BASE, "repos")
ENV_FILE = os.path.expanduser("~/.hermes/.env")
TOPIC = "hermes-kb"
CODELOAD = "https://codeload.github.com"


def load_token():
    tok = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if tok:
        return tok
    if os.path.exists(ENV_FILE):
        for line in open(ENV_FILE, encoding="utf-8"):
            line = line.strip()
            if line.startswith(("GITHUB_TOKEN=", "GH_TOKEN=")):
                return line.split("=", 1)[1].strip()
    return None


def load_user(token):
    u = os.environ.get("GITHUB_USER")
    if u:
        return u
    if os.path.exists(ENV_FILE):
        for line in open(ENV_FILE, encoding="utf-8"):
            if line.strip().startswith("GITHUB_USER="):
                return line.split("=", 1)[1].strip()
    return None


def gh_api(path, token):
    req = urllib.request.Request(
        f"https://api.github.com{path}",
        headers={"Authorization": f"Bearer {token}",
                 "Accept": "application/vnd.github+json",
                 "User-Agent": "hermes-kb-sync"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def discover_repos(token, user):
    """按 topic 自动发现知识库仓库。"""
    repos = []
    try:
        for page in range(1, 4):
            data = gh_api(f"/search/repositories?q=topic:{TOPIC}+user:{user}"
                          f"&per_page=100&page={page}", token)
            items = data.get("items", [])
            repos.extend(x["name"] for x in items)
            if len(items) < 100:
                break
    except Exception as e:                           # noqa: BLE001
        print(f"!! topic 发现失败({e}),回退到列举账号下仓库")
    if not repos:
        try:
            for page in range(1, 4):
                data = gh_api(f"/user/repos?per_page=100&page={page}"
                              f"&affiliation=owner", token)
                repos.extend(x["name"] for x in data if x["name"].startswith("kb-"))
                if len(data) < 100:
                    break
        except Exception as e:                       # noqa: BLE001
            print(f"!! 仓库列举失败: {e}")
    return sorted(set(repos))


def fetch_repo(repo, user, token):
    """经 codeload 拉 tarball 并解压到 ~/.hermes/kb/repos/<repo>/"""
    url = f"{CODELOAD}/{user}/{repo}/tar.gz/refs/heads/main"
    dest = os.path.join(REPOS_DIR, repo)
    tmp = dest + ".tmp"
    t0 = time.time()
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {token}", "User-Agent": "hermes-kb-sync"})
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            raw = r.read()
    except Exception as e:                           # noqa: BLE001
        print(f"  ❌ {repo}: 下载失败 {e}")
        return None
    dt = time.time() - t0
    speed = len(raw) / dt / 1024 / 1024 if dt else 0
    print(f"  ⬇️  {repo}: {len(raw) / 1024 / 1024:.1f} MB / {dt:.1f}s "
          f"= {speed:.1f} MB/s")

    if os.path.exists(tmp):
        shutil.rmtree(tmp)
    os.makedirs(tmp, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as tf:
        members = tf.getmembers()
        if not members:
            return None
        root = members[0].name.split("/")[0]         # 顶层目录名
        tf.extractall(tmp, filter="data")
    src = os.path.join(tmp, root)
    if os.path.exists(dest):
        shutil.rmtree(dest)
    shutil.move(src, dest)
    shutil.rmtree(tmp, ignore_errors=True)

    ndocs = 0
    for sub in ("docs/en", "docs/zh", "docs"):
        p = os.path.join(dest, sub)
        if os.path.isdir(p):
            ndocs += len([f for f in os.listdir(p) if f.endswith(".md")])
    print(f"     → {dest}  ({ndocs} 篇)")
    return dest


def rebuild_index():
    here = os.path.dirname(os.path.abspath(__file__))
    idx = os.path.join(here, "kb_index.py")
    db = os.path.join(BASE, "index.db")
    if not os.path.exists(idx):
        print(f"!! 找不到 {idx},跳过索引")
        return
    # 把所有仓库的 docs 汇总成一个临时根,再建索引
    merged = os.path.join(BASE, "_merged")
    if os.path.exists(merged):
        shutil.rmtree(merged)
    os.makedirs(os.path.join(merged, "docs"), exist_ok=True)
    for repo in sorted(os.listdir(REPOS_DIR)):
        for sub in ("en", "zh"):
            src = os.path.join(REPOS_DIR, repo, "docs", sub)
            if not os.path.isdir(src):
                continue
            dst = os.path.join(merged, "docs", sub)
            os.makedirs(dst, exist_ok=True)
            for f in os.listdir(src):
                if f.endswith(".md"):
                    new = f"{repo}__{f}" if os.path.exists(os.path.join(dst, f)) else f
                    shutil.copy2(os.path.join(src, f), os.path.join(dst, new))
    subprocess.run([sys.executable, idx, merged, "--db", db], check=False)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", action="append", default=[])
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--no-index", action="store_true")
    a = ap.parse_args()

    token = load_token()
    if not token:
        print("!! 未找到 GITHUB_TOKEN(检查 ~/.hermes/.env)")
        sys.exit(1)
    user = load_user(token)
    if not user:
        print("!! 未找到 GITHUB_USER")
        sys.exit(1)

    repos = a.repo or discover_repos(token, user)
    print(f"知识库仓库({len(repos)}): {', '.join(repos) or '(无)'}")
    if a.list:
        return

    os.makedirs(REPOS_DIR, exist_ok=True)
    ok = 0
    for r in repos:
        if fetch_repo(r, user, token):
            ok += 1
    print(f"\n同步完成: {ok}/{len(repos)}")

    if not a.no_index:
        print("\n重建索引 …")
        rebuild_index()


if __name__ == "__main__":
    main()
