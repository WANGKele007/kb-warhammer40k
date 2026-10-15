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


def search(db_path, query, lang=None, limit=8):
    db = sqlite3.connect(db_path)
    results = []
    q = _sanitize(query)
    if not q:
        return results
    for table, mode in (("fts_tri", "trigram"), ("fts_zh", "word")):
        try:
            sql = (f"SELECT d.lang,d.title,d.url,d.path,"
                   f" snippet({table},1,'《','》','…',18) AS snip, bm25({table}) AS score "
                   f"FROM {table} JOIN docs d ON d.id={table}.rowid "
                   f"WHERE {table} MATCH ? ")
            params = [f'"{q}"' if mode == "trigram" else q]
            if lang:
                sql += "AND d.lang=? "
                params.append(lang)
            sql += "ORDER BY score LIMIT ?"
            params.append(limit)
            rows = db.execute(sql, params).fetchall()
            if rows:
                results = [dict(zip(("lang", "title", "url", "path", "snippet", "score"), r))
                           for r in rows]
                break
        except sqlite3.OperationalError:
            continue
    db.close()
    return results


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("kb_root", nargs="?", default=".")
    ap.add_argument("--db", default=DEFAULT_DB)
    ap.add_argument("--search", default=None)
    ap.add_argument("--lang", default=None)
    ap.add_argument("--limit", type=int, default=8)
    a = ap.parse_args()

    if a.search:
        res = search(a.db, a.search, a.lang, a.limit)
        if not res:
            print("(无命中)")
        for r in res:
            print(f"[{r['lang']}] {r['title']}")
            print(f"    {r['url'] or r['path']}")
            print(f"    {r['snippet'][:220]}")
            print()
        return

    os.makedirs(os.path.dirname(a.db), exist_ok=True)
    build(a.kb_root, a.db)


if __name__ == "__main__":
    main()
