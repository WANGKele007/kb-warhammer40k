#!/usr/bin/env python3
"""
采集 wh40knews.com/lore 中文背景设定与故事 → docs/zh/*.md

本地直连运行(该站未被墙)。实测 132 篇。

⚠️ 合规说明(用户 2026-10-15 明确决定采用方案 A):
   该站 robots.txt 明确 Disallow 全部 AI 爬虫(GPTBot / ClaudeBot / CCBot /
   Google-Extended / OAI-SearchBot / ChatGPT-User),但对 Googlebot/Bingbot/
   Baiduspider 放行。
   本项目为**个人自用知识库**(不用于模型训练、不再分发),用户已知悉并选择采集。
   本脚本据此采取合规约束:
     · 严格限速 1 秒/页
     · 只抓一次,不设定时任务
     · 每篇保留原文 URL 与来源标注
     · 不抓 /news、/guides(用户已排除)
"""
import html
import json
import os
import re
import sys
import time
import urllib.robotparser

import requests

SITE = "https://wh40knews.com"
SITEMAP = f"{SITE}/sitemap.xml"
OUTDIR = "docs/zh"
SOURCE_ID = "wh40knews"
DELAY = 1.0                     # 秒/页,严格遵守
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

# 用户已明确知悉并批准(见文件头合规说明)
USER_APPROVED_AI_BOT_DISALLOW = True

S = requests.Session()
S.headers.update({"User-Agent": UA, "Accept-Language": "zh-CN,zh;q=0.9"})


def log(m):
    print(m, flush=True)


def preflight():
    log("=" * 60)
    log("robots.txt 合规预检")
    log("=" * 60)
    r = S.get(f"{SITE}/robots.txt", timeout=30)
    r.raise_for_status()
    text = r.text
    with open("robots_snapshot_zh.txt", "w", encoding="utf-8") as f:
        f.write(f"# {SITE}/robots.txt\n# {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}\n")
        f.write(text)

    rp = urllib.robotparser.RobotFileParser()
    rp.parse(text.splitlines())

    ok = rp.can_fetch(UA, f"{SITE}/lore/test")
    log(f"  本采集器 UA 抓 /lore/ : {'✅ 允许' if ok else '❌ 禁止'}")

    ai_blocked = [a for a in ("GPTBot", "ClaudeBot", "CCBot", "Google-Extended",
                              "OAI-SearchBot", "ChatGPT-User")
                  if not rp.can_fetch(a, f"{SITE}/lore/x")]
    if ai_blocked:
        log(f"  ⚠️  该站 Disallow 的 AI 爬虫: {', '.join(ai_blocked)}")
        log("     本站明示意图:不希望内容喂给 AI。本项目为个人自用知识库。")
        if not USER_APPROVED_AI_BOT_DISALLOW:
            log("!! 未获用户批准 —— 中止")
            sys.exit(2)
        log("     → 用户已明确批准采集(方案 A),继续\n")
    if not ok:
        log("!! robots.txt 禁止本 UA 抓取 /lore —— 中止")
        sys.exit(2)
    log("→ 预检通过\n")


def lore_urls():
    r = S.get(SITEMAP, timeout=30)
    r.raise_for_status()
    urls = re.findall(r"<loc>([^<]+)</loc>", r.text)
    lore = [u for u in urls if "/lore/" in u]
    log(f"sitemap 共 {len(urls)} 条 URL,其中 /lore/ {len(lore)} 条\n")
    return lore


def extract_content(page):
    """从页面里取出 id=post-content 的正文容器。"""
    m = re.search(r'<div[^>]*id="post-content"[^>]*>(.*)', page, re.S)
    if not m:
        return None, None
    body = m.group(1)
    # 截到容器结束:取到下一个 </div> 平衡点过于复杂,用启发式 —— 到 <footer 或脚注
    for stop in ("<footer", 'id="footer', "<script"):
        i = body.find(stop)
        if i > 500:
            body = body[:i]
    title = None
    tm = re.search(r"<h1[^>]*>(.*?)</h1>", page, re.S)
    if tm:
        title = re.sub(r"<[^>]+>", "", tm.group(1))
        title = html.unescape(title).strip()
    return body, title


def html_to_md(h):
    t = h
    t = re.sub(r"<(script|style|nav|footer|svg)[^>]*>.*?</\1>", "", t, flags=re.S | re.I)
    t = re.sub(r"<br\s*/?>", "\n", t, flags=re.I)
    for i in range(1, 7):
        t = re.sub(rf"<h{i}[^>]*>(.*?)</h{i}>",
                   lambda m, i=i: "\n" + "#" * i + " " + m.group(1).strip() + "\n",
                   t, flags=re.S | re.I)
    t = re.sub(r"<li[^>]*>(.*?)</li>", lambda m: "- " + m.group(1).strip() + "\n",
               t, flags=re.S | re.I)
    t = re.sub(r"<blockquote[^>]*>(.*?)</blockquote>",
               lambda m: "\n> " + m.group(1).strip() + "\n", t, flags=re.S | re.I)
    t = re.sub(r"<(b|strong)[^>]*>(.*?)</\1>", r"**\2**", t, flags=re.S | re.I)
    t = re.sub(r"<(i|em)[^>]*>(.*?)</\1>", r"*\2*", t, flags=re.S | re.I)
    t = re.sub(r'<a[^>]*href="([^"]*)"[^>]*>(.*?)</a>',
               lambda m: f"[{re.sub(r'<[^>]+>', '', m.group(2)).strip()}]({m.group(1)})"
               if not m.group(1).startswith("#") else m.group(2), t, flags=re.S | re.I)
    t = re.sub(r"<img[^>]*alt=\"([^\"]*)\"[^>]*/?>", r"", t, flags=re.I)
    t = re.sub(r"<p[^>]*>", "\n\n", t, flags=re.I)
    t = re.sub(r"</(p|div|ul|ol|h[1-6])>", "\n", t, flags=re.I)
    t = re.sub(r"<[^>]+>", "", t)
    t = html.unescape(t)
    t = re.sub(r"[ \t\u00a0]+", " ", t)
    t = re.sub(r"\n\s*\n\s*\n+", "\n\n", t)
    return t.strip()


def main():
    preflight()
    urls = lore_urls()
    if not urls:
        log("!! 未找到 /lore 条目")
        sys.exit(1)

    os.makedirs(OUTDIR, exist_ok=True)
    index = []
    failed = []
    for i, u in enumerate(urls, 1):
        slug = u.rstrip("/").split("/")[-1]
        try:
            r = S.get(u, timeout=30)
            r.raise_for_status()
            body, title = extract_content(r.text)
            if not body:
                failed.append((u, "未找到 post-content"))
                log(f"  [{i}/{len(urls)}] ❌ {slug} (无正文容器)")
                time.sleep(DELAY)
                continue
            md = html_to_md(body)
            title = title or slug
            fm = ["---", f'title: "{title}"', f"url: {u}",
                  f"source: {SOURCE_ID}", "lang: zh", "---"]
            with open(os.path.join(OUTDIR, f"{slug}.md"), "w", encoding="utf-8") as f:
                f.write("\n".join(fm) + "\n\n" + md + "\n")
            index.append({"title": title, "slug": slug, "url": u,
                          "chars": len(md), "bytes": len(md.encode())})
            if i % 10 == 0 or i == len(urls):
                log(f"  [{i}/{len(urls)}] ✅ {slug} ({len(md)} 字)")
        except Exception as e:                       # noqa: BLE001
            failed.append((u, str(e)[:80]))
            log(f"  [{i}/{len(urls)}] ❌ {slug}: {str(e)[:60]}")
        time.sleep(DELAY)

    with open(os.path.join(OUTDIR, "_index.json"), "w", encoding="utf-8") as f:
        json.dump({"source": SOURCE_ID, "count": len(index),
                   "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                   "pages": index, "failed": failed}, f, ensure_ascii=False, indent=2)

    total = sum(x["bytes"] for x in index)
    log(f"\n✅ 完成: {len(index)}/{len(urls)} 篇,正文合计 {total / 1024:.0f} KB")
    if failed:
        log(f"⚠️  失败 {len(failed)} 篇:")
        for u, why in failed:
            log(f"    {u} — {why}")


if __name__ == "__main__":
    main()
