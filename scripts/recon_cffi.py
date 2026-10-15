#!/usr/bin/env python3
"""用 curl_cffi(TLS 指纹伪装)在 GitHub Actions 上重测候选源。
目的:判断 Actions + curl_cffi 能否替代临时 VPS。"""
import time
from curl_cffi import requests as cr

SRC = [
 ("Lexicanum EN",  "https://wh40k.lexicanum.com/wiki/Main_Page", "lore"),
 ("Lexicanum DE",  "https://wh40k-de.lexicanum.com/wiki/Hauptseite", "lore"),
 ("Lexicanum FR",  "https://wh40k-fr.lexicanum.com/wiki/Accueil", "lore"),
 ("Lexicanum API", "https://wh40k.lexicanum.com/api.php?action=query&meta=siteinfo&format=json", "lore"),
 ("Fandom API",    "https://warhammer40k.fandom.com/api.php?action=query&meta=siteinfo&format=json", "lore"),
 ("Reddit old",    "https://old.reddit.com/r/40kLore/", "culture"),
 ("Wikipedia",     "https://en.wikipedia.org/wiki/Warhammer_40,000", "culture"),
 ("1d4chan",       "https://1d4chan.org/wiki/Warhammer_40,000", "culture"),
 ("Spikey Bits",   "https://spikeybits.com/", "media"),
 ("Wahapedia",     "https://wahapedia.ru/wh40k10ed/the-rules/core-rules/", "rules"),
 ("WH Shop",       "https://www.warhammer.com/en-GB/home", "official"),
 ("NGA",           "https://bbs.nga.cn/", "zh"),
 ("百度百科",       "https://baike.baidu.com/item/%E6%88%98%E9%94%A440K", "zh"),
 ("贴吧",          "https://tieba.baidu.com/f?kw=%E6%88%98%E9%94%A440k", "zh"),
 ("知乎话题",       "https://www.zhihu.com/topic/19586681", "zh"),
 ("gcores",        "https://www.gcores.com/", "zh"),
 ("bilibili",      "https://www.bilibili.com/", "zh"),
]

s = cr.Session(impersonate="chrome124")
print(f"{'源':<16}{'类别':<9}{'HTTP':<7}{'字节':<10}判定")
print("-" * 58)
for name, url, cat in SRC:
    try:
        r = s.get(url, timeout=40)
        cf = ("Just a moment" in r.text) or ("Attention Required" in r.text)
        ok = r.status_code == 200 and not cf and len(r.text) > 1500
        v = "✅ OK" if ok else ("⚠️ CF挑战" if cf else f"❌ {r.status_code}")
        print(f"{name:<16}{cat:<9}{r.status_code:<7}{len(r.text):<10}{v}", flush=True)
    except Exception as e:                                       # noqa: BLE001
        print(f"{name:<16}{cat:<9}{'ERR':<7}{'':<10}❌ {str(e)[:40]}", flush=True)
    time.sleep(0.5)
