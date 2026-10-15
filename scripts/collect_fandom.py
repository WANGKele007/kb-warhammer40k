#!/usr/bin/env python3
"""
采集 Fandom Warhammer 40K Wiki 全量正文 → docs/en/*.md

在 GitHub Actions 上运行(墙外)。实测规模:7,313 篇 / 80MB wikitext。

设计:
  · 开跑前强制 robots.txt 预检,不合规直接中止(exit 2)
  · 优先用 TextExtracts 拿渲染后的纯文本(干净);
    若不可用则自动回退到 wikitext + 正则清洗
  · 单篇写成带 YAML frontmatter 的 .md
"""
import json
import os
import re
import sys
import time
import unicodedata
import urllib.robotparser
from collections import OrderedDict

import requests

API = "https://warhammer40k.fandom.com/api.php"
SITE = "https://warhammer40k.fandom.com"
UA = "hermes-personal-kb/1.0 (personal, non-redistributed knowledge base; owner: WANGKele007)"
OUTDIR = "docs/en"
SOURCE_ID = "fandom-wh40k"

S = requests.Session()
S.headers.update({"User-Agent": UA})

MAX_FILES = int(os.environ.get("KB_MAX_FILES", "0"))     # 0 = 不限


# ------------------------------------------------------------------ 工具
def log(msg):
    print(msg, flush=True)


def api(**params):
    p = {"format": "json", "formatversion": "2", **params}
    last = None
    for attempt in range(5):
        try:
            r = S.get(API, params=p, timeout=60)
            if r.status_code == 429:
                time.sleep(5 * (attempt + 1))
                continue
            r.raise_for_status()
            return r.json()
        except Exception as e:                       # noqa: BLE001
            last = e
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"API 失败 {params}: {last}")


def slugify(title):
    s = unicodedata.normalize("NFKD", title)
    s = s.replace("/", "-").replace(":", "-")
    s = re.sub(r"[^\w\s\-.,()']", "", s, flags=re.UNICODE)
    s = re.sub(r"[\s_]+", "_", s).strip("_.")
    return (s or "page")[:180]


# ---------------------------------------------------- robots.txt 合规预检
def preflight_robots():
    log("=" * 60)
    log("robots.txt 合规预检")
    log("=" * 60)
    rp = urllib.robotparser.RobotFileParser()
    url = f"{SITE}/robots.txt"
    try:
        r = S.get(url, timeout=30)
        r.raise_for_status()
        rp.parse(r.text.splitlines())
    except Exception as e:                           # noqa: BLE001
        log(f"!! 无法取得 robots.txt: {e}")
        log("!! 保守起见中止采集")
        sys.exit(2)

    checks = [
        f"{SITE}/wiki/Main_Page",
        f"{SITE}/api.php?action=query&meta=siteinfo&format=json",
    ]
    bad = []
    for u in checks:
        ok = rp.can_fetch(UA, u)
        log(f"  {'✅' if ok else '❌'} can_fetch: {u[:70]}")
        if not ok:
            bad.append(u)

    # 显式检查 AI 爬虫是否被禁(提示用,不强制中止 —— 由站方规则对具体 UA 判定)
    for agent in ("GPTBot", "ClaudeBot", "CCBot", "Google-Extended"):
        if not rp.can_fetch(agent, f"{SITE}/wiki/Main_Page"):
            log(f"  ⚠️  robots.txt 对 {agent} 设了 Disallow(本采集器 UA 不同,按自身规则判定)")

    if bad:
        log(f"\n!! robots.txt 不允许本采集器抓取 {len(bad)} 个路径 —— 中止")
        sys.exit(2)
    log("→ 预检通过\n")


# ------------------------------------------------------------ 枚举全部页面
def enumerate_pages():
    log("=" * 60)
    log("枚举主命名空间条目")
    log("=" * 60)
    titles = []
    cont = None
    while True:
        p = dict(action="query", list="allpages", apnamespace=0,
                 apfilterredir="nonredirects", aplimit=500)
        if cont:
            p["apcontinue"] = cont
        d = api(**p)
        batch = [x["title"] for x in d.get("query", {}).get("allpages", [])]
        titles.extend(batch)
        cont = d.get("continue", {}).get("apcontinue")
        log(f"  已枚举 {len(titles)}")
        if not cont:
            break
        time.sleep(0.1)
    log(f"→ 共 {len(titles)} 个条目\n")
    return titles


def enumerate_redirects():
    rmap = {}
    cont = None
    while True:
        p = dict(action="query", list="allpages", apnamespace=0,
                 apfilterredir="redirects", aplimit=500)
        if cont:
            p["apcontinue"] = cont
        d = api(**p)
        rmap.update({x["title"]: True for x in d.get("query", {}).get("allpages", [])})
        cont = d.get("continue", {}).get("apcontinue")
        if not cont:
            break
        time.sleep(0.1)
    return rmap


# ------------------------------------------------------ wikitext 清洗(回退)
def wikitext_to_text(wt):
    t = wt
    t = re.sub(r"<!--.*?-->", "", t, flags=re.S)
    t = re.sub(r"<ref[^>]*/>", "", t, flags=re.I)
    t = re.sub(r"<ref[^>]*>.*?</ref>", "", t, flags=re.S | re.I)
    # 嵌套模板
    for _ in range(12):
        n = re.sub(r"\{\{[^{}]*\}\}", "", t)
        if n == t:
            break
        t = n
    t = re.sub(r"\{\|.*?\|\}", "", t, flags=re.S)          # 表格
    t = re.sub(r"^\s*\[\[(Category|File|Image):.*?\]\]\s*$", "", t,
               flags=re.M | re.I)
    t = re.sub(r"\[\[(?:[^\]|]*\|)?([^\]|]*)\]\]", r"\1", t)   # 内链
    t = re.sub(r"\[(?:https?://\S+)\s+([^\]]*)\]", r"\1", t)   # 外链
    t = re.sub(r"\[(?:https?://\S+)\]", "", t)
    t = re.sub(r"^={2,}\s*(.*?)\s*={2,}$", r"\n## \1\n", t, flags=re.M)  # 标题
    t = t.replace("'''", "").replace("''", "")             # 粗斜体
    t = re.sub(r"<[^>]+>", "", t)                          # 残留标签
    t = re.sub(r"^[*#:;]+\s*", "", t, flags=re.M)          # 列表符号
    t = re.sub(r"\n{3,}", "\n\n", t)
    t = re.sub(r"[ \t]{2,}", " ", t)
    return t.strip()


# ------------------------------------------------------------ 抓取正文
def fetch_extracts(titles, cache):
    """TextExtracts:渲染后的纯文本,每批 20 篇。返回成功篇数。"""
    BATCH = 20
    got = 0
    for i in range(0, len(titles), BATCH):
        chunk = titles[i:i + BATCH]
        try:
            d = api(action="query", titles="|".join(chunk), prop="extracts",
                    explaintext=1, exlimit=BATCH, redirects=0)
        except Exception as e:                       # noqa: BLE001
            log(f"  [extracts] 批次 {i} 失败: {e}")
            continue
        for p in d.get("query", {}).get("pages", []):
            ex = p.get("extract")
            if ex and len(ex) > 50:
                cache[p["title"]] = {"text": ex, "pageid": p.get("pageid"),
                                     "extract": True}
                got += 1
        if i % (BATCH * 25) == 0:
            log(f"  [extracts] {i + len(chunk)}/{len(titles)} … 成功 {got}")
        time.sleep(0.05)
    return got


def fetch_wikitext(titles, cache):
    """回退:取 wikitext 再正则清洗,每批 50 篇。"""
    BATCH = 50
    for i in range(0, len(titles), BATCH):
        chunk = titles[i:i + BATCH]
        try:
            d = api(action="query", titles="|".join(chunk),
                    prop="revisions", rvprop="content|timestamp",
                    rvslots="main")
        except Exception as e:                       # noqa: BLE001
            log(f"  [wikitext] 批次 {i} 失败: {e}")
            continue
        for p in d.get("query", {}).get("pages", []):
            revs = p.get("revisions") or []
            if not revs:
                continue
            slot = (revs[0].get("slots") or {}).get("main") or {}
            wt = slot.get("content") or ""
            if not wt:
                continue
            cache[p["title"]] = {
                "text": wikitext_to_text(wt),
                "pageid": p.get("pageid"),
                "updated": revs[0].get("timestamp"),
                "extract": False,
            }
        if i % (BATCH * 10) == 0:
            log(f"  [wikitext] {i + len(chunk)}/{len(titles)} … 成功 {len(cache)}")
        time.sleep(0.05)
    return len(cache)


# ---------------------------------------------------------------- 主流程
def main():
    preflight_robots()

    titles = enumerate_pages()
    if MAX_FILES:
        titles = titles[:MAX_FILES]
        log(f"!! 限量模式:只处理前 {MAX_FILES} 篇\n")

    # --- 正文来源:优先 extracts
    log("=" * 60)
    log("抓取正文 (模式:TextExtracts 优先)")
    log("=" * 60)
    cache = OrderedDict()
    got = fetch_extracts(titles, cache)
    mode = "extracts"
    if got < len(titles) * 0.5:
        log(f"\n!! extracts 只拿到 {got}/{len(titles)},回退到 wikitext 模式")
        cache.clear()
        fetch_wikitext(titles, cache)
        mode = "wikitext"
    log(f"→ 模式={mode},共拿到 {len(cache)} 篇\n")

    # --- 写盘
    log("=" * 60)
    log("写出 markdown")
    log("=" * 60)
    os.makedirs(OUTDIR, exist_ok=True)
    index = []
    used = set()
    for title, rec in cache.items():
        slug = slugify(title)
        while slug in used:
            slug += "_"
        used.add(slug)
        path = os.path.join(OUTDIR, f"{slug}.md")
        fm = [
            "---",
            f'title: "{title.replace(chr(34), chr(39))}"',
            f"pageid: {rec.get('pageid')}",
            f"url: {SITE}/wiki/{title.replace(' ', '_')}",
            f"source: {SOURCE_ID}",
            "lang: en",
        ]
        if rec.get("updated"):
            fm.append(f"updated: {rec['updated']}")
        fm.append("---")
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(fm) + "\n\n" + rec["text"] + "\n")
        index.append({"title": title, "slug": slug,
                      "pageid": rec.get("pageid"),
                      "bytes": len(rec["text"])})

    with open(os.path.join(OUTDIR, "_index.json"), "w", encoding="utf-8") as f:
        json.dump({"source": SOURCE_ID, "mode": mode, "count": len(index),
                   "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                   "pages": index}, f, ensure_ascii=False)

    total = sum(x["bytes"] for x in index)
    log(f"\n✅ 完成: {len(index)} 篇,正文合计 {total / 1024 / 1024:.1f} MB,模式={mode}")


if __name__ == "__main__":
    main()
