# kb-warhammer40k

战锤 40K(Warhammer 40,000)知识库 —— 英文原典 + 中文原生内容,统一中文检索。

## 现状:已跑通 ✅

| 源 | 语言 | 篇数 | 正文体积 | 采集方式 |
|---|---|---|---|---|
| Fandom WH40K Wiki | en | **7,313** | 69.5 MB | GitHub Actions |
| wh40knews.com `/lore` | zh | **887** | 15.2 MB | 本地直连(API) |
| **合计** | | **8,200** | **85 MB** | |

本地索引:SQLite FTS5,320 MB,中英统一检索。

## 怎么用

```bash
# 同步所有知识库 + 重建索引
python tools/kb_sync.py

# 检索(中文提问会经术语表扩展,同时命中英文原库)
python tools/kb_index.py . --search "帝皇" --glossary
python tools/kb_index.py . --search "基因原体" --limit 5
```

## 架构

```
[英文源] Fandom WH40K Wiki ──GitHub Actions──┐
[中文源] wh40knews.com/lore ──本地直连───────┤
                                             ▼
                                    本库 docs/{en,zh}/*.md
                                             │ codeload 17MB/s
                                             ▼
                                    SQLite FTS5 (三套索引)
                                             │
              中文提问 ─术语表扩展─> 中英双库检索 ─翻译─> 中文回答
```

**关键设计**:英文库存原文(权威、完整),中文库存原生内容(无需翻译)。
查询时用 `glossary/glossary.json` 把中文词映射成英文检索词,两库同时命中。

索引三套并行:
- `fts_en` — porter 词干,英文检索
- `fts_zh` — unicode61 分词,中文分词
- `fts_tri` — trigram,中文任意子串检索(最可靠)

## 目录结构

```
├── docs/en/            7,313 篇英文正文(带 YAML frontmatter)
├── docs/zh/              132 篇中文正文
├── glossary/
│   └── glossary.json   中英术语对照表(93 条,持续积累)
├── scripts/
│   ├── recon.py        侦察:测量规模,不下载内容
│   ├── collect_fandom.py  英文源采集器(含 robots 预检)
│   └── collect_zh.py      中文源采集器(限速 1s/页)
├── tools/
│   ├── kb_index.py     本地 FTS5 索引器 + 术语表驱动检索
│   └── kb_sync.py      codeload 同步 + 索引重建
└── .github/workflows/
    ├── recon.yml
    └── collect-fandom.yml
```

## ⚠️ 合规记录

| 源 | robots.txt | 处置 |
|---|---|---|
| **Fandom** | `/robots.txt` 返回 **403 — Cloudflare "Just a moment..." 挑战页**(对任意 UA、任意路径均如此) | 判定为 **CDN 对机房 IP 的反爬**,非站点禁止声明。依据:① `api.php` 为平台官方接口且可正常访问;② 内容许可为 **CC-BY-SA**(Fandom 官方授权再利用,需署名)。**每篇均保留来源 URL 署名。** 留档 `robots_unavailable.txt` |
| **wh40knews** | **Disallow 全部 AI 爬虫**(GPTBot/ClaudeBot/CCBot/Google-Extended/OAI-SearchBot/ChatGPT-User);Googlebot 等放行 | 站方明示意图为"不希望内容喂给 AI"。本项目为**个人自用知识库**(不训练、不再分发),用户 2026-10-15 明确批准方案 A。措施:**严格限速 1s/页**、只抓一次不设定时、保留原文 URL、不抓 /news 与 /guides |

## ⚠️ 网络约束(踩过的坑)

- ✅ **codeload.github.com 拉取** — 实测 **17 MB/s**(tarball 通道,首选)
- ❌ **Release 资产** — 实测 **19 KB/s**,不可用
- ❌ **raw.githubusercontent.com** — 被墙
- ❌ **Git LFS** — 媒体下载走 `media.githubusercontent.com`,大概率被墙
- ❌ **Fandom 直连** — SNI 阻断;`wh40k.lexicanum.com` — Cloudflare 拦机房 IP;两者均须走 Actions
- ⏱️ **Actions 配额** — 公开库无限,私有库 2000 分钟/月

## 采集节奏

按需触发(`workflow_dispatch`),不设定时任务 —— 省配额,上游更新不需要实时同步。

## 待办

- [ ] 术语表扩充(当前 93 条 → 目标覆盖核心 500+ 条),可从中文库行文中自动挖掘英文词
- [ ] 高频条目预翻译(可选,当前不需要)
- [ ] Lexicanum 第二英文源(可选,覆盖面翻倍)
