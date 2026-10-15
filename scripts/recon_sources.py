#!/usr/bin/env python3
"""
候选源可达性探测 —— 在 GitHub Actions 机房(墙外)上运行。

目的: 判断"用 Actions 就够了"还是"必须有额外跳板(VPS)"。
对每个源输出: HTTP 状态 / 耗时 / 是否被 Cloudflare 挑战 / 正文样本长度
"""
import json
import re
import time

import requests

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

SOURCES = [
    # (名称, URL, 类别)
    ("Lexicanum EN",      "https://wh40k.lexicanum.com/wiki/Main_Page", "lore"),
    ("Lexicanum DE",      "https://wh40k-de.lexicanum.com/wiki/Hauptseite", "lore"),
    ("Lexicanum API",     "https://wh40k.lexicanum.com/api.php?action=query&meta=siteinfo&format=json", "lore"),
    ("Fandom WH40K API",  "https://warhammer40k.fandom.com/api.php?action=query&meta=siteinfo&format=json", "lore"),
    ("1d4chan",           "https://1d4chan.org/wiki/Warhammer_40,000", "culture"),
    ("Reddit r/40kLore",  "https://www.reddit.com/r/40kLore/top.json?t=all&limit=5", "culture"),
    ("Reddit WH40k",      "https://www.reddit.com/r/Warhammer40k/top.json?t=all&limit=5", "culture"),
    ("Wikipedia WH40K",   "https://en.wikipedia.org/wiki/Warhammer_40,000", "culture"),
    ("Wahapedia",         "https://wahapedia.ru/", "rules"),
    ("Wahapedia rules",   "https://wahapedia.ru/wh40k10ed/the-rules/core-rules/", "rules"),
    ("WH Community",      "https://www.warhammer-community.com/", "official"),
    ("WH Shop",           "https://www.warhammer.com/", "official"),
    ("Goonhammer",        "https://www.goonhammer.com/", "media"),
    ("Wargamer",          "https://www.wargamer.com/", "media"),
    ("Dicebreaker",       "https://www.dicebreaker.com/", "media"),
    ("Spikey Bits",       "https://spikeybits.com/", "media"),
    ("gcores 机核",        "https://www.gcores.com/", "zh-culture"),
    ("bilibili",          "https://www.bilibili.com/", "zh-culture"),
    ("NGA 战锤版",         "https://bbs.nga.cn/", "zh-culture"),
    ("百度百科 战锤",       "https://baike.baidu.com/item/%E6%88%98%E9%94%A440K", "zh-culture"),
    ("贴吧 战锤40k",        "https://tieba.baidu.com/f?kw=%E6%88%98%E9%94%A440k", "zh-culture"),
    ("知乎 战锤话题",        "https://www.zhihu.com/topic/19586681", "zh-culture"),
    ("游民星空",           "https://www.gamersky.com/", "zh-media"),
]


def probe(name, url, cat):
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"})
    t0 = time.time()
    try:
        r = s.get(url, timeout=25, allow_redirects=True)
        dt = time.time() - t0
        body = r.text or ""
        cf = bool(re.search(r"Just a moment|Attention Required|cf-browser-verification"
                            r"|__cf_chl|Enable JavaScript and cookies", body, re.I))
        rb = ""
        low = body.lower()
        if "robots" in url or True:
            pass
        # 粗略正文量:去标签后字符数
        txt = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", body, flags=re.S | re.I)
        txt = re.sub(r"<[^>]+>", " ", txt)
        txt = re.sub(r"\s+", " ", txt).strip()
        ok = r.status_code == 200 and len(txt) > 800 and not cf
        return {
            "name": name, "url": url, "category": cat,
            "status": r.status_code, "elapsed": round(dt, 2),
            "final_url": r.url[:120], "bytes": len(body), "text_chars": len(txt),
            "cloudflare": cf, "verdict": "OK" if ok else
            ("CF-挑战" if cf else f"HTTP {r.status_code}"),
            "sample": txt[:150],
        }
    except Exception as e:                                     # noqa: BLE001
        return {"name": name, "url": url, "category": cat,
                "status": "ERR", "elapsed": round(time.time() - t0, 2),
                "verdict": f"失败: {str(e)[:70]}", "sample": ""}


def main():
    results = []
    print(f"{'源':<20} {'类别':<11} {'HTTP':<6} {'耗时':<7} {'正文':<9} 判定")
    print("-" * 88)
    for name, url, cat in SOURCES:
        r = probe(name, url, cat)
        results.append(r)
        print(f"{name:<20} {cat:<11} {str(r['status']):<6} "
              f"{str(r['elapsed'])+'s':<7} {str(r.get('text_chars','')):<9} {r['verdict']}",
              flush=True)
        time.sleep(0.6)

    good = [r for r in results if r["verdict"] == "OK"]
    cf = [r for r in results if "CF" in r["verdict"]]
    bad = [r for r in results if r["verdict"] not in ("OK",) and "CF" not in r["verdict"]]

    print("\n" + "=" * 88)
    print(f"✅ 可用 {len(good)} | ⚠️ Cloudflare挑战 {len(cf)} | ❌ 失败 {len(bad)}")
    print("\n--- Cloudflare 挑战的源 ---")
    for r in cf:
        print(f"  {r['name']}: {r['status']} {r['url']}")
    print("\n--- 失败的源 ---")
    for r in bad:
        print(f"  {r['name']}: {r['verdict']}")

    with open("source_recon.json", "w", encoding="utf-8") as f:
        json.dump({"runner": "github-actions", "results": results},
                  f, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
