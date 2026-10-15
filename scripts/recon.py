#!/usr/bin/env python3
"""
侦察脚本 — 不下载任何正文内容,只测量 wiki 规模。

用途:
  1. 拿站点统计(条目数 / 总页数 / 图片数)
  2. 抽样测量页面 wikitext 字节数 → 外推全站体积
  3. 探测是否存在中文版 wiki(Fandom 跨语言链接)
  4. 试探热门条目名,为后续抓取做准备

产物: recon_report.json (由 workflow 提交回仓库)
"""
import json
import sys
import time

import requests

API = "https://warhammer40k.fandom.com/api.php"
UA = "hermes-kb-recon/1.0 (personal knowledge base; owner: WANGKele007)"
SAMPLE_LIMIT = 500          # 每次 API 最多 500 条
SAMPLE_BUCKETS = None       # None = 用全部起始字母

S = requests.Session()
S.headers.update({"User-Agent": UA})


def api(**params):
    """带重试的 API 调用。"""
    p = {"format": "json", "formatversion": "2", **params}
    last = None
    for attempt in range(4):
        try:
            r = S.get(API, params=p, timeout=30)
            r.raise_for_status()
            return r.json()
        except Exception as e:            # noqa: BLE001
            last = e
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"API 调用失败: {params} -> {last}")


def section(title):
    print(f"\n{'=' * 60}\n{title}\n{'=' * 60}", flush=True)


report = {"api": API, "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}

# ---------------------------------------------------------------- 1. 站点统计
section("1. 站点统计 (siteinfo)")
si = api(action="query", meta="siteinfo", siprop="general|statistics|namespaces")
report["siteinfo"] = si.get("query", {})
g = report["siteinfo"].get("general", {})
st = report["siteinfo"].get("statistics", {})
print(f"站点名   : {g.get('sitename')}")
print(f"主语言   : {g.get('lang')}")
print(f"条目数   : {st.get('articles'):,}" if st.get("articles") else "条目数   : ?")
print(f"总页数   : {st.get('pages'):,}" if st.get("pages") else "总页数   : ?")
print(f"编辑次数 : {st.get('edits'):,}" if st.get("edits") else "编辑次数 : ?")
print(f"图片文件 : {st.get('images'):,}" if st.get("images") else "图片文件 : ?")

# ------------------------------------------------------- 2. 中文版存在性探测
section("2. 中文版 wiki 探测")
lang_probe = {"langlinks": {}, "candidate_urls": {}, "zh_wiki_exists": False}

for title in ["Main Page", "Imperium", "Space Marine", "Chaos", "Emperor of Mankind"]:
    try:
        d = api(action="query", titles=title, prop="langlinks", lllimit=500)
        pages = d.get("query", {}).get("pages", [])
        links = []
        if pages:
            links = pages[0].get("langlinks", []) or []
        lang_probe["langlinks"][title] = {l["lang"]: l["title"] for l in links}
        zh = [l["title"] for l in links if l["lang"].startswith("zh")]
        print(f"  {title:22s} -> {len(links)} 个语言版本" + (f" | 中文: {zh}" if zh else ""))
        if zh:
            lang_probe["zh_wiki_exists"] = True
    except Exception as e:                                          # noqa: BLE001
        print(f"  {title:22s} -> 失败: {e}")
    time.sleep(0.2)

# 直接探测候选中文站 URL
for url in [
    "https://warhammer40k.fandom.com/zh",
    "https://zh.warhammer40k.fandom.com/wiki/Main_Page",
    "https://warhammer40k.fandom.com/zh/wiki/Main_Page",
]:
    try:
        r = S.get(url, timeout=20, allow_redirects=True)
        lang_probe["candidate_urls"][url] = {"status": r.status_code, "final": r.url}
        print(f"  {url:52s} -> {r.status_code}")
    except Exception as e:                                          # noqa: BLE001
        lang_probe["candidate_urls"][url] = {"status": "error", "detail": str(e)[:120]}
        print(f"  {url:52s} -> 失败")
    time.sleep(0.2)

report["lang_probe"] = lang_probe

# ------------------------------------------------------- 3. 页面大小抽样
section("3. 页面体积抽样")
if SAMPLE_BUCKETS is None:
    starts = [None] + [chr(c) for c in range(ord("A"), ord("Z") + 1)] + ["0", "9"]
else:
    starts = [None] + [chr(c) for c in range(ord("A"), ord("A") + SAMPLE_BUCKETS)]

lengths = []
for i, st_char in enumerate(starts, 1):
    params = dict(
        action="query",
        generator="allpages",
        gaplimit=SAMPLE_LIMIT,
        gapfilterredir="nonredirects",
        prop="info",
    )
    if st_char:
        params["gapfrom"] = st_char
    try:
        d = api(**params)
    except Exception as e:                                          # noqa: BLE001
        print(f"  bucket {st_char or 'start':6s} 失败: {e}")
        continue
    pages = d.get("query", {}).get("pages", []) or []
    got = [p["length"] for p in pages if p.get("length") and not p.get("redirect")]
    lengths.extend(got)
    print(f"  bucket {str(st_char or 'start'):6s} 采到 {len(got):4d} 页 | 累计 {len(lengths)}",
          flush=True)
    time.sleep(0.25)

if not lengths:
    print("!! 抽样失败,无法外推体积")
    report["sampling"] = {"error": "no samples"}
else:
    lengths.sort()
    n = len(lengths)
    avg = sum(lengths) / n
    pct = lambda q: lengths[min(n - 1, int(n * q))]        # noqa: E731
    articles = st.get("articles") or st.get("pages") or 0
    raw = avg * articles

    report["sampling"] = {
        "sample_count": n,
        "avg_bytes": round(avg, 1),
        "median_bytes": pct(0.5),
        "p10_bytes": pct(0.10),
        "p90_bytes": pct(0.90),
        "max_bytes": lengths[-1],
        "min_bytes": lengths[0],
        "total_length_bytes": sum(lengths),
    }
    report["extrapolation"] = {
        "articles_used": articles,
        "raw_wikitext_MB": round(raw / 1024 / 1024, 1),
        "raw_wikitext_GB": round(raw / 1024 / 1024 / 1024, 2),
        "est_plaintext_MB": round(raw * 0.85 / 1024 / 1024, 1),
        "est_gzip_MB": round(raw * 0.85 * 0.25 / 1024 / 1024, 1),
        "note": "gzip 按 4:1 压缩比估算;纯文本按 wikitext 85% 估算",
    }

    print(f"\n  样本数     : {n:,}")
    print(f"  平均字节   : {avg:,.0f} B")
    print(f"  中位数     : {pct(0.5):,} B")
    print(f"  P90        : {pct(0.90):,} B")
    print(f"  最大       : {lengths[-1]:,} B")
    print(f"\n  条目数     : {articles:,}")
    print(f"  → wikitext 全量 : {raw / 1024 / 1024 / 1024:.2f} GB")
    print(f"  → 纯文本估算    : {raw * 0.85 / 1024 / 1024:.0f} MB")
    print(f"  → gzip 后估算   : {raw * 0.85 * 0.25 / 1024 / 1024:.0f} MB")

# ------------------------------------------------------- 4. 热门条目名试探
section("4. 关键条目存在性试探 (为抓取铺路)")
probe_titles = [
    "Imperium", "Space Marine", "Chaos", "Emperor of Mankind", "Horus Heresy",
    "Adeptus Astartes", "Necrons", "Tyranids", "Eldar", "Orks", "Aeldari",
    "Gene-seed", "Warp", "Primarch", "Great Crusade", "Tyranid Hive Fleets",
]
found = {}
CHUNK = 20
for i in range(0, len(probe_titles), CHUNK):
    batch = probe_titles[i:i + CHUNK]
    try:
        d = api(action="query", titles="|".join(batch), prop="info")
        for p in d.get("query", {}).get("pages", []):
            missing = p.get("missing")
            found[p.get("title")] = {
                "exists": not missing,
                "length": p.get("length"),
                "pageid": p.get("pageid"),
            }
    except Exception as e:                                          # noqa: BLE001
        print(f"  批次失败: {e}")
    time.sleep(0.2)

ok = sum(1 for v in found.values() if v["exists"])
print(f"  {ok}/{len(found)} 个关键条目存在")
for t, v in sorted(found.items()):
    print(f"    {'✅' if v['exists'] else '❌'} {t:24s} {v.get('length') or ''}")
report["title_probe"] = found

# ---------------------------------------------------------------- 输出
with open("recon_report.json", "w", encoding="utf-8") as f:
    json.dump(report, f, ensure_ascii=False, indent=2)

section("完成")
print("报告已写入 recon_report.json")
print(json.dumps(report.get("extrapolation", {}), ensure_ascii=False, indent=2))
