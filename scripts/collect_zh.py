#!/usr/bin/env python3
"""
采集 wh40knews.com「战锤40K宇宙背景设定」全部 887 篇 → docs/zh/*.md

⚠️ 为什么用 CMS API 而不是爬页面(重要教训)
   最初我用 sitemap.xml 枚举,只得 132 篇 —— 因为**该站 sitemap 严重不完整**。
   实测该分类实际有 **887 篇**,漏了 755 篇(85%)。
   站点是 Next.js + Payload CMS 前端,翻页由客户端 JS 完成,`?page=N` 无效。
   最终定位到 Payload 后端 REST API(公开可达),数据完整且是结构化正文。

数据源:
   前端  https://wh40knews.com          (Next.js,受 robots 限制 AI 爬虫)
   后端  https://thousandrealms.win/api/contents   (Payload CMS)
         robots.txt 仅 Disallow /admin/*,/api/* 未被禁止

筛选:
   website.id = 110   战锤40K指南网
   categories.id = 326  战锤40K宇宙背景设定 (slug: lore)
   _status = published

合规:个人自用知识库(用户 2026-10-15 批准方案 A)。限速、只抓一次、保留原文 URL 署名。
"""
import html as _html
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.robotparser

import requests

API = "https://thousandrealms.win/api/contents"
CMS_HOST = "https://thousandrealms.win"
SITE_URL = "https://wh40knews.com"
OUTDIR = "docs/zh"
SOURCE_ID = "wh40knews"

WEBSITE_ID = 110
CATEGORY_ID = 326
LIMIT = 100                      # 每页条数(API 上限一般 100)
DELAY = 1.0                      # 请求间隔(仅约 9 个请求)
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

USER_APPROVED = True             # 用户已知悉前端 robots 限制并批准

S = requests.Session()
S.headers.update({"User-Agent": UA})


def log(m):
    print(m, flush=True)


# ------------------------------------------------------------ robots 预检
def preflight():
    log("=" * 62)
    log("robots.txt 合规预检")
    log("=" * 62)
    # 1) CMS 后端
    try:
        r = S.get(f"{CMS_HOST}/robots.txt", timeout=30)
        rp = urllib.robotparser.RobotFileParser()
        rp.parse(r.text.splitlines())
        ok_api = rp.can_fetch(UA, f"{CMS_HOST}/api/contents")
        log(f"  [CMS 后端] {CMS_HOST}/api/contents  ->  {'✅ 允许' if ok_api else '❌ 禁止'}")
        for line in r.text.splitlines()[:12]:
            log("      " + line)
        if not ok_api:
            log("!! CMS API 被 robots 禁止 —— 中止")
            sys.exit(2)
    except Exception as e:                            # noqa: BLE001
        log(f"  [CMS 后端] robots 获取失败: {e} —— 保守中止")
        sys.exit(2)

    # 2) 前端(站方 Disallow AI 爬虫,用户已批准)
    try:
        r = S.get(f"{SITE_URL}/robots.txt", timeout=30)
        rp = urllib.robotparser.RobotFileParser()
        rp.parse(r.text.splitlines())
        ai = [a for a in ("GPTBot", "ClaudeBot", "CCBot", "Google-Extended",
                          "OAI-SearchBot", "ChatGPT-User")
              if not rp.can_fetch(a, f"{SITE_URL}/lore/x")]
        log(f"  [前端] {SITE_URL}  Disallow 的 AI 爬虫: {', '.join(ai) or '(无)'}")
        log(f"     本采集器 UA 抓取许可: {rp.can_fetch(UA, f'{SITE_URL}/lore/x')}")
        if ai and not USER_APPROVED:
            log("!! 未获用户批准 —— 中止")
            sys.exit(2)
        log("     → 用户已批准(个人自用知识库,方案 A)")
    except Exception as e:                            # noqa: BLE001
        log(f"  [前端] robots 获取失败: {e}")
    log("→ 预检通过\n")


# --------------------------------------------------- Lexical JSON → markdown
FMT_BOLD, FMT_ITALIC, FMT_STRIKE, FMT_UNDER, FMT_CODE = 1, 2, 4, 8, 16


def _text_node(n):
    t = n.get("text", "")
    f = n.get("format", 0)
    if f & FMT_CODE:
        t = f"`{t}`"
    if f & FMT_BOLD:
        t = f"**{t}**"
    if f & FMT_ITALIC:
        t = f"*{t}*"
    if f & FMT_STRIKE:
        t = f"~~{t}~~"
    return t


def lex_nodes(nodes, out, depth=0):
    for n in nodes or []:
        if not isinstance(n, dict):
            continue
        t = n.get("type")
        kids = n.get("children") or []
        if t == "text":
            out.append(_text_node(n))
        elif t == "linebreak":
            out.append("\n")
        elif t == "link":
            label = "".join(
                _text_node(k) for k in kids if isinstance(k, dict) and k.get("type") == "text")
            url = ""
            for f in (n.get("fields") or {}).values():
                if isinstance(f, dict) and f.get("url"):
                    url = f["url"]
            out.append(f"[{label}]({url})" if url else label)
        elif t == "heading":
            tag = n.get("tag") or "h2"
            lvl = int(tag[1]) if tag[1:].isdigit() else 2
            out.append("\n" + "#" * lvl + " ")
            lex_nodes(kids, out, depth)
            out.append("\n")
        elif t == "list":
            out.append("\n")
            for li in kids:
                if isinstance(li, dict):
                    out.append("- ")
                    lex_nodes(li.get("children") or [], out, depth + 1)
                    out.append("\n")
            out.append("\n")
        elif t == "listitem":
            lex_nodes(kids, out, depth)
        elif t == "quote":
            out.append("\n> ")
            lex_nodes(kids, out, depth)
            out.append("\n")
        elif t == "paragraph":
            lex_nodes(kids, out, depth)
            out.append("\n\n")
        elif t == "block":
            out.append("\n")
        elif kids:
            lex_nodes(kids, out, depth)


def lexical_to_md(content):
    if not isinstance(content, dict):
        return ""
    out = []
    lex_nodes((content.get("root") or {}).get("children"), out)
    t = "".join(out)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()


def html_to_md(h):
    t = re.sub(r"<(script|style|nav|footer|svg)[^>]*>.*?</\1>", "", h, flags=re.S | re.I)
    t = re.sub(r"<br\s*/?>", "\n", t, flags=re.I)
    for i in range(1, 7):
        t = re.sub(rf"<h{i}[^>]*>(.*?)</h{i}>",
                   lambda m, i=i: "\n" + "#" * i + " " + m.group(1).strip() + "\n",
                   t, flags=re.S | re.I)
    t = re.sub(r"<li[^>]*>(.*?)</li>", lambda m: "- " + m.group(1).strip() + "\n",
               t, flags=re.S | re.I)
    t = re.sub(r"<(b|strong)[^>]*>(.*?)</\1>", r"**\2**", t, flags=re.S | re.I)
    t = re.sub(r"<(i|em)[^>]*>(.*?)</\1>", r"*\2*", t, flags=re.S | re.I)
    t = re.sub(r'<a[^>]*href="([^"]*)"[^>]*>(.*?)</a>',
               lambda m: f"[{re.sub(r'<[^>]+>','',m.group(2)).strip()}]({m.group(1)})",
               t, flags=re.S | re.I)
    t = re.sub(r"<img[^>]*>", "", t, flags=re.I)
    t = re.sub(r"<p[^>]*>", "\n\n", t, flags=re.I)
    t = re.sub(r"</(p|div|ul|ol|h[1-6])>", "\n", t, flags=re.I)
    t = re.sub(r"<[^>]+>", "", t)
    t = _html.unescape(t)
    t = re.sub(r"[ \t\u00a0]+", " ", t)
    t = re.sub(r"\n\s*\n\s*\n+", "\n\n", t)
    return t.strip()


# ------------------------------------------------------------------ 抓取
def fetch_all():
    where = [
        ("where[and][0][websiteCategories.categories.id][in]", str(CATEGORY_ID)),
        ("where[and][1][websiteCategories.website.id][equals]", str(WEBSITE_ID)),
        ("where[and][2][_status][equals]", "published"),
    ]
    docs, page, total = [], 1, None
    while True:
        params = where + [("depth", "0"), ("limit", str(LIMIT)), ("page", str(page))]
        url = API + "?" + urllib.parse.urlencode(params)
        r = S.get(url, timeout=90)
        r.raise_for_status()
        d = r.json()
        total = d.get("totalDocs", 0)
        got = d.get("docs", [])
        docs.extend(got)
        tp = d.get("totalPages", 1)
        log(f"  page {page}/{tp} → 累计 {len(docs)}/{total}")
        if page >= tp or not got:
            break
        page += 1
        time.sleep(DELAY)
    return docs, total


def main():
    preflight()
    log("=" * 62)
    log(f"抓取 contents: website={WEBSITE_ID}, category={CATEGORY_ID}")
    log("=" * 62)
    docs, total = fetch_all()
    log(f"→ 共取回 {len(docs)} 篇 (API 报告 totalDocs={total})\n")

    os.makedirs(OUTDIR, exist_ok=True)
    # 清掉旧的 sitemap 版采集结果
    old = [f for f in os.listdir(OUTDIR) if f.endswith(".md")]
    for f in old:
        os.remove(os.path.join(OUTDIR, f))
    log(f"(已清空旧采集 {len(old)} 篇)\n")

    index, fails = [], []
    for i, doc in enumerate(docs, 1):
        slug = doc.get("slug") or f"content-{doc.get('id')}"
        title = (doc.get("title") or slug).replace('"', "'")
        body = html_to_md(doc.get("contentHtml") or "")
        if len(body) < 80:                       # 回退到 Lexical
            body = lexical_to_md(doc.get("content"))
        if len(body) < 40:
            fails.append((slug, "正文为空"))
            continue
        fm = ["---", f'title: "{title}"',
              f"url: {SITE_URL}/lore/{slug}",
              f"source: {SOURCE_ID}", "lang: zh"]
        if doc.get("originalPublishedAt"):
            fm.append(f"published: {doc['originalPublishedAt']}")
        if doc.get("sourceUrl"):
            fm.append(f"original_url: {doc['sourceUrl']}")
        fm.append("---")
        with open(os.path.join(OUTDIR, f"{slug}.md"), "w", encoding="utf-8") as f:
            f.write("\n".join(fm) + "\n\n" + body + "\n")
        index.append({"title": doc.get("title"), "slug": slug,
                      "id": doc.get("id"), "url": f"{SITE_URL}/lore/{slug}",
                      "chars": len(body), "bytes": len(body.encode()),
                      "published": doc.get("originalPublishedAt")})
        if i % 100 == 0:
            log(f"  写入 {i}/{len(docs)} …")

    with open(os.path.join(OUTDIR, "_index.json"), "w", encoding="utf-8") as f:
        json.dump({"source": SOURCE_ID, "api": API,
                   "website_id": WEBSITE_ID, "category_id": CATEGORY_ID,
                   "category_title": "战锤40K宇宙背景设定",
                   "count": len(index), "api_total": total,
                   "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                   "pages": index, "failed": fails}, f, ensure_ascii=False, indent=1)

    tot = sum(x["bytes"] for x in index)
    log(f"\n✅ 完成: {len(index)}/{total} 篇,正文合计 {tot/1024/1024:.1f} MB")
    if fails:
        log(f"⚠️  跳过 {len(fails)} 篇(正文为空)")


if __name__ == "__main__":
    main()
