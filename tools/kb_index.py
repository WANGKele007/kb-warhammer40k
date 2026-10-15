#!/usr/bin/env python3
"""
kb_index.py — 扫描知识库仓库里的 docs/**,建 SQLite FTS5 全文索引。

中英双库统一索引。中文用 unicode61 分词 + 英文用 porter 词干,
通过 FTS5 的 trigram / unicode61 组合支撑中文子串检索。

用法:
    python kb_index.py <kb_root> [--db ~/.hermes/kb/index.db]
    python kb_index.py <kb_root> --search "星际战士"
"""
import argparse
import json
import os
import re
import sqlite3
import sys
import time
from pathlib import Path

DEFAULT_DB = os.path.expanduser("~/.hermes/kb/index.db")


def parse_frontmatter(text):
    """解析 YAML frontmatter(只处理简单 key: value)。"""
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end == -1:
        return {}, text
    head, body = text[3:end], text[end + 4:]
    meta = {}
    for line in head.splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            meta[k.strip()] = v.strip().strip('"').strip("'")
    return meta, body.lstrip("\n")


def iter_docs(kb_root):
    for src_dir in sorted(Path(kb_root).glob("docs/*")):
        if not src_dir.is_dir():
            continue
        lang = src_dir.name
        for md in sorted(src_dir.glob("*.md")):
            text = md.read_text(encoding="utf-8", errors="replace")
            meta, body = parse_frontmatter(text)
            yield {
                "lang": meta.get("lang", lang),
                "title": meta.get("title", md.stem),
                "url": meta.get("url", ""),
                "source": meta.get("source", ""),
                "updated": meta.get("updated", ""),
                "path": str(md.relative_to(kb_root)),
                "body": body,
            }


SCHEMA = """
DROP TABLE IF EXISTS docs;
DROP TABLE IF EXISTS fts_en;
DROP TABLE IF EXISTS fts_zh;
DROP TABLE IF EXISTS fts_tri;

CREATE TABLE docs (
    id        INTEGER PRIMARY KEY,
    lang      TEXT, title TEXT, url TEXT, source TEXT,
    updated   TEXT, path TEXT, body TEXT
);
CREATE INDEX idx_docs_lang  ON docs(lang);
CREATE INDEX idx_docs_title ON docs(title);

-- 英文:porter 词干
CREATE VIRTUAL TABLE fts_en USING fts5(
    title, body, content='docs', content_rowid='id', tokenize='porter unicode61'
);

-- 中文:unicode61 分词
CREATE VIRTUAL TABLE fts_zh USING fts5(
    title, body, content='docs', content_rowid='id', tokenize='unicode61'
);

-- trigram:支撑任意语言子串检索(中文短查询最可靠)
CREATE VIRTUAL TABLE fts_tri USING fts5(
    title, body, content='docs', content_rowid='id', tokenize='trigram'
);
"""


def build(kb_root, db_path):
    db = sqlite3.connect(db_path)
    db.executescript(SCHEMA)

    n = 0
    for d in iter_docs(kb_root):
        cur = db.execute(
            "INSERT INTO docs(lang,title,url,source,updated,path,body) "
            "VALUES(?,?,?,?,?,?,?)",
            (d["lang"], d["title"], d["url"], d["source"],
             d["updated"], d["path"], d["body"]))
        rid = cur.lastrowid
        db.execute("INSERT INTO fts_en(rowid,title,body) VALUES(?,?,?)",
                   (rid, d["title"], d["body"]))
        db.execute("INSERT INTO fts_zh(rowid,title,body) VALUES(?,?,?)",
                   (rid, d["title"], d["body"]))
        db.execute("INSERT INTO fts_tri(rowid,title,body) VALUES(?,?,?)",
                   (rid, d["title"], d["body"]))
        n += 1

    db.commit()

    stats = {}
    for t in ("fts_en", "fts_zh", "fts_tri"):
        stats[t] = db.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
    lang_counts = dict(db.execute(
        "SELECT lang, count(*) FROM docs GROUP BY lang").fetchall())
    size = os.path.getsize(db_path)

    db.execute("CREATE TABLE IF NOT EXISTS _meta(key TEXT PRIMARY KEY, value TEXT)")
    db.execute("INSERT OR REPLACE INTO _meta VALUES(?,?)",
               ("built_at", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())))
    db.commit()
    db.close()

    print(f"✅ 索引完成: {n} 篇")
    print(f"   语言分布 : {lang_counts}")
    print(f"   索引体积 : {size / 1024 / 1024:.1f} MB")
    print(f"   位置     : {db_path}")
    return n


def _sanitize(q):
    """FTS5 查询串清洗:去掉会触发语法错误的字符。"""
    q = re.sub(r'["\(\)\*\^:]', " ", q)
    return q.strip()


# ---------------------------------------------------------------- 术语表
_GLOSSARY_CACHE = {}


def load_glossary(kb_root):
    """载入中英术语表(本库优先,兼容多库合并)。"""
    key = os.path.abspath(kb_root)
    if key in _GLOSSARY_CACHE:
        return _GLOSSARY_CACHE[key]
    entries = []
    cands = [os.path.join(kb_root, "glossary", "glossary.json")]
    parent = os.path.dirname(os.path.abspath(kb_root))
    for d in (parent, os.path.expanduser("~/.hermes/kb/repos")):
        if os.path.isdir(d):
            for sub in os.listdir(d):
                cands.append(os.path.join(d, sub, "glossary", "glossary.json"))
    seen = set()
    dedup = set()
    out = []
    for c in cands:
        if not os.path.exists(c) or c in seen:
            continue
        seen.add(c)
        try:
            data = json.load(open(c, encoding="utf-8"))
            for e in data.get("entries", []):
                k = (e.get("zh", ""), e.get("en", ""))
                if k in dedup or not k[0]:
                    continue
                dedup.add(k)
                out.append(e)
        except Exception:                            # noqa: BLE001
            pass
    _GLOSSARY_CACHE[key] = out
    return out


def expand_query(query, kb_root):
    """中文查询 → 英文检索词。返回 (命中条目, 英文词列表)。"""
    hits, en_terms = [], []
    ql = query.lower()
    for e in load_glossary(kb_root):
        names = [e.get("zh", "")] + list(e.get("alias_zh") or [])
        for n in names:
            if n and n.lower() in ql:
                hits.append(e)
                for t in [e.get("en", "")] + list(e.get("alias_en") or []):
                    if t and t not in en_terms:
                        en_terms.append(t)
                break
    return hits, en_terms


def _fts_search(db, table, q, lang, limit):
    sql = (f"SELECT d.lang,d.title,d.url,d.path,d.source,"
           f" snippet({table},1,'《','》','…',18) AS snip, bm25({table}) AS score "
           f"FROM {table} JOIN docs d ON d.id={table}.rowid "
           f"WHERE {table} MATCH ? ")
    params = [q]
    if lang:
        sql += "AND d.lang=? "
        params.append(lang)
    sql += "ORDER BY score LIMIT ?"
    params.append(limit)
    return [dict(zip(("lang", "title", "url", "path", "source", "snippet", "score"), r))
            for r in db.execute(sql, params).fetchall()]


def search(db_path, query, lang=None, limit=8, kb_root="."):
    db = sqlite3.connect(db_path)
    q = _sanitize(query)
    if not q:
        db.close()
        return [], []

    # 1) 中文/原样检索
    results = []
    for table, mode in (("fts_tri", "trigram"), ("fts_zh", "word")):
        try:
            results = _fts_search(db, table,
                                  f'"{q}"' if mode == "trigram" else q, lang, limit)
            if results:
                break
        except sqlite3.OperationalError:
            continue

    # 2) 术语表扩展 → 英文原库检索
    hits, en_terms = expand_query(query, kb_root)
    if en_terms:
        seen = {r["path"] for r in results}
        extra = []
        for t in en_terms[:4]:
            try:
                got = _fts_search(db, "fts_en", f'"{_sanitize(t)}"',
                                  "en" if lang is None else lang, max(3, limit // 2))
            except sqlite3.OperationalError:
                continue
            for r in got:
                if r["path"] not in seen:
                    seen.add(r["path"])
                    r["snippet"] = f"[命中术语: {t}] " + r["snippet"]
                    extra.append(r)
        # 英文命中排前面(原典权威),中文命中随后
        results = extra + results

    db.close()
    return results[:limit], hits


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("kb_root", nargs="?", default=".")
    ap.add_argument("--db", default=DEFAULT_DB)
    ap.add_argument("--search", default=None)
    ap.add_argument("--lang", default=None)
    ap.add_argument("--limit", type=int, default=8)
    ap.add_argument("--glossary", action="store_true", help="打印术语表命中情况")
    a = ap.parse_args()

    if a.search:
        res, hits = search(a.db, a.search, a.lang, a.limit, a.kb_root)
        if hits and a.glossary:
            print("术语表命中:", ", ".join(f"{h['zh']}→{h['en']}" for h in hits))
            print()
        if not res:
            print("(无命中)")
        for r in res:
            print(f"[{r['lang']}] {r['title']}")
            print(f"    {r['url'] or r['path']}")
            print(f"    {r['snippet'][:200]}")
            print()
        return

    os.makedirs(os.path.dirname(a.db), exist_ok=True)
    build(a.kb_root, a.db)


if __name__ == "__main__":
    main()
