# kb-warhammer40k

战锤 40K(Warhammer 40,000)知识库。

## 这个库是干什么的

把上游资料采集下来做成本地可全文检索的知识库,用中文提问、中文作答。

**英文源**提供权威原典(存英文原文,查询时翻译);
**中文源**提供中文原生内容(直接可用,无需翻译)。

数据流向:

```
[英文源] Fandom WH40K Wiki ──GitHub Actions──┐
[英文源] Lexicanum        ──GitHub Actions──┤
[中文源] wh40knews.com/lore ──本地直连───────┤
                                             ▼
                                     本库 (docs/*.md)
                                             │ codeload / 本地
                                             ▼
                                    本地 SQLite FTS5 索引
                                             │
                    中文提问 ─术语表─> 检索 ─LLM翻译─> 中文回答
```

## 上游数据源

| 源 | 语言 | 地址 | 直连? | 采集方式 | 状态 |
|---|---|---|---|---|---|
| **Fandom WH40K Wiki** | en | warhammer40k.fandom.com | ❌ SNI 阻断 | GitHub Actions | 侦察待跑 |
| Lexicanum | en | wh40k.lexicanum.com | ❌ Cloudflare 拦 | GitHub Actions | 暂缓 |
| **战锤 40K 中文站** | **zh** | wh40knews.com | ✅ 直连正常 | 本地 | ⚠️ 见下 |

### ⚠️ wh40knews.com 的 robots.txt 问题

该站 `robots.txt` **明确禁止全部 AI 爬虫**:

```
User-agent: GPTBot       Disallow: /
User-agent: ChatGPT-User Disallow: /
User-agent: Google-Extended Disallow: /
User-agent: CCBot        Disallow: /
User-agent: ClaudeBot    Disallow: /
User-agent: OAI-SearchBot
```

(Googlebot / Bingbot / Baiduspider 则 Allow)

**含义**:站方不欢迎 AI 抓取其内容。本项目是**个人自用知识库**(不训练、不再分发),与"AI 训练爬取"性质不同,但这是站方明示意图,需用户明确决策后再动手。

采集范围(若获准):仅 `/lore` 目录 **132 篇**背景设定与故事;`/news`(37 篇资讯)、`/guides`(14 篇攻略)按用户要求排除。

## 目录结构

```
.
├── README.md
├── manifest.json          # 机器可读元数据
├── recon_report.json      # 侦察结果(站点规模实测)
├── scripts/
│   ├── recon.py           # 侦察:测量 Fandom 规模,不下载内容
│   ├── collect_fandom.py  # 采集英文源(待建)
│   └── collect_zh.py      # 采集中文源(待建)
├── docs/                  # 采集到的正文,每篇一个 .md
├── glossary/              # 中英术语对照表(待建)
└── .github/workflows/
    └── recon.yml
```

## ⚠️ 约束(踩过的坑,别再踩)

- ❌ **不用 Release 传数据** — 实测 19 KB/s,不可用
- ✅ **用 codeload.github.com 拉取** — 实测 17 MB/s
- ❌ **不依赖 raw.githubusercontent.com** — 被墙
- ❌ **不用 Git LFS** — 媒体下载走 `media.githubusercontent.com`,大概率被墙
- ❌ **不存原始 HTML / 二进制** — 体积膨胀 5~10 倍,只存清洗后的文本
- ⏱️ **Actions 配额** — 公开库无限,私有库 2000 分钟/月

## 采集节奏

按需触发,不设定时任务 — 省配额,上游更新不需要实时同步。
