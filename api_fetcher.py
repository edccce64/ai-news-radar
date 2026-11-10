import os
import re
import time
from datetime import date, timedelta

import requests

import rss_fetcher
from config import (
    AGGREGATOR_LIMIT,
    AGGREGATOR_URL,
    GITHUB_CREATED_DAYS,
    GITHUB_LIMIT,
    GITHUB_PER_TOPIC,
    GITHUB_TOPICS,
    PER_SOURCE_LIMIT,
    SHOWHN_KEYWORDS,
    SHOWHN_LIMIT,
    SHOWHN_MIN_POINTS,
    SHOWHN_PER_KEYWORD,
    TOOL_FEEDS,
)

TIMEOUT = 30

# SkillsHub 标题形如「#1 laya — ★ 30.2k (2.0k/day)」
_GROWTH_RE = re.compile(r"★\s*([\d.]+)\s*([kmKM]?)\s*\(\s*([\d.]+)\s*([kmKM]?)\s*/day\s*\)")
_SCALE = {"": 1, "k": 1e3, "m": 1e6}


def _strip_rank(items):
    """去掉内部排序键 _rank，只留对外字段。"""
    return [{k: v for k, v in i.items() if k != "_rank"} for i in items]


def _skillhub_rate(title):
    """从 SkillsHub 标题取**相对增速**（日增/总星）。

    绝对日增会让 39 万星的老项目（1.3k/天 = 0.33%）压过 3 万星的新项目
    （2k/天 = 6.6%）。要「冒头的」就得按相对增速排。
    """
    m = _GROWTH_RE.search(title or "")
    if not m:
        return 0.0
    total = float(m.group(1)) * _SCALE.get(m.group(2).lower(), 1)
    daily = float(m.group(3)) * _SCALE.get(m.group(4).lower(), 1)
    return daily / total if total else 0.0


def _clean_tool_title(title):
    """SkillsHub 标题形如 '#5 AIHOT — ★ 4.9k (1.2k/day)'，去掉排名和数据尾巴。"""
    t = re.sub(r"^#\d+\s+", "", title or "")
    t = re.sub(r"\s*—\s*★.*$", "", t)
    return t.strip() or (title or "")


def fetch_github(limit=GITHUB_LIMIT) -> list[dict]:
    """GitHub 上「近期新建 + star 排序」的 AI 仓库，当 trending 用。

    官方没有 trending API；OSSInsight 的 trending 自 2026-03 起数据停摆。
    多 topic 不支持 OR（HTTP 422），必须逐 topic 循环。
    """
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        print("[警告] 无 GITHUB_TOKEN，跳过 GitHub 源（Actions 上会自动注入）")
        return []

    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "User-Agent": "AI-News-search",
    }
    recent = (date.today() - timedelta(days=GITHUB_CREATED_DAYS)).isoformat()
    seen = {}

    for topic in GITHUB_TOPICS:
        try:
            resp = requests.get(
                "https://api.github.com/search/repositories",
                params={
                    "q": f"topic:{topic} created:>{recent}",
                    "sort": "stars",
                    "order": "desc",
                    "per_page": GITHUB_PER_TOPIC,
                },
                headers=headers,
                timeout=TIMEOUT,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            # 200 但不是 JSON（代理页、维护页）也会走到这，单独包住避免整轮崩
            print(f"[警告] GitHub topic={topic} 抓取失败，跳过：{type(exc).__name__}")
            continue

        for it in data.get("items", []):
            if it["full_name"] in seen:
                continue
            stars = it.get("stargazers_count", 0)
            created = (it.get("created_at") or "")[:10]
            try:
                age = max((date.today() - date.fromisoformat(created)).days, 1)
            except ValueError:
                age = 1
            seen[it["full_name"]] = {
                "source": "GitHub Trending",
                "title": it["full_name"],
                "link": it["html_url"],
                "summary": (
                    f"{rss_fetcher._clean(it.get('description') or '')}"
                    f"（★{stars}，创建 {age} 天，{it.get('open_issues_count', 0)} 个 issue）"
                ),
                "kind": "tool",
                # 星/天：新建 + 涨得猛的优先，天然压制老项目
                "_rank": stars / age,
            }
        time.sleep(2)  # 搜索限流 30 次/分（带 token）

    out = sorted(seen.values(), key=lambda x: x["_rank"], reverse=True)[:limit]
    print(f"[OK] GitHub Trending: {len(out)} 条")
    return _strip_rank(out)


def fetch_showhn(limit=SHOWHN_LIMIT) -> list[dict]:
    """Show HN 的 AI 工具发布帖。走 Algolia，不走 hnrss（偶发 502）。

    坑：多关键词 OR 组合 numericFilters 会返回 0 条，必须逐词请求后按 objectID 合并。
    """
    since = int(time.time()) - 24 * 3600
    seen = {}

    for kw in SHOWHN_KEYWORDS:
        try:
            resp = requests.get(
                "https://hn.algolia.com/api/v1/search_by_date",
                params={
                    "query": kw,
                    "tags": "show_hn",
                    "numericFilters": f"points>={SHOWHN_MIN_POINTS},created_at_i>={since}",
                    "hitsPerPage": SHOWHN_PER_KEYWORD,
                },
                timeout=TIMEOUT,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            print(f"[警告] Show HN 关键词 {kw} 抓取失败，跳过：{type(exc).__name__}")
            continue

        for h in data.get("hits", []):
            oid = h["objectID"]
            if oid in seen:
                continue
            seen[oid] = {
                "source": "Show HN",
                "title": rss_fetcher._clean(h.get("title", "")),
                "link": h.get("url") or f"https://news.ycombinator.com/item?id={oid}",
                # Show HN 常常只有标题，没有描述；有 story_text 就带上，
                # 否则 LLM 只能靠标题脑补（会产生空洞分析）
                "summary": (
                    f"{rss_fetcher._clean(h.get('story_text') or h.get('title') or '')[:200]}"
                    f"（Show HN 发布，{h.get('points', 0)} points，"
                    f"{h.get('num_comments', 0)} 条评论）"
                ),
                "kind": "tool",
                # 讨论最多的优先（用户要「讨论最多」）
                "_rank": h.get("num_comments", 0),
            }

    out = sorted(seen.values(), key=lambda x: x["_rank"], reverse=True)[:limit]
    print(f"[OK] Show HN: {len(out)} 条")
    return _strip_rank(out)


def fetch_aggregator(limit=AGGREGATOR_LIMIT) -> list[dict]:
    """SuYxh/ai-news-aggregator 的 24h 聚合快照：80+ AI/科技源，每 2 小时更新。

    纯 JSON（**没有 RSS feed**，实测 feed.xml 等全 404），带中英双语标题。
    ⚠️ schema 里**没有摘要字段**，只有标题+链接 —— 当「捞头条」用，
    深度加工靠模型背景知识，容易触发 skip/低质量过滤，属预期行为。
    24h 窗口实测 821 条、146 个来源，故每源只取最新 1 条保证多样性。
    """
    try:
        resp = requests.get(AGGREGATOR_URL, timeout=TIMEOUT)
        resp.raise_for_status()
        raw = resp.json().get("items", [])
    except Exception as exc:
        print(f"[警告] AI 聚合源抓取失败，跳过：{exc}")
        return []

    def _time(it):
        """条目的时间：优先发布时间，否则首次出现时间。"""
        return it.get("published_at") or it.get("first_seen_at") or ""

    # 聚合源的中文翻译覆盖约 55%（153/276 英文条目），未翻译的 title_zh 为 null。
    # 用户要求「全都要中文」，故有中文标题的优先，同档再按时间新旧排。
    out, seen_source = [], set()
    for it in sorted(raw, key=lambda x: (bool(x.get("title_zh")), _time(x)), reverse=True):
        src = it.get("source") or it.get("site_name") or ""
        if not src or src in seen_source:
            continue
        seen_source.add(src)

        title = it.get("title_zh") or it.get("title_bilingual") or it.get("title") or ""
        original = it.get("title_original") or title
        out.append(
            {
                "source": src,
                "title": rss_fetcher._clean(title),
                "link": it.get("url", ""),
                # 无摘要字段，只能给原文标题 + 时间；留给模型自己用背景知识补
                "summary": rss_fetcher._clean(f"原文标题：{original}｜时间：{_time(it)}"),
                "kind": "news",
            }
        )
        if len(out) >= limit:
            break

    print(f"[OK] AI 聚合（80+ 源，{len(raw)} 条中取 {len(out)}）")
    return out


def fetch_tools() -> list[dict]:
    """工具/Skill 全量：agent-skills-hub 的两个 RSS 源 + GitHub + Show HN。

    各源先按自己的「冒头度」排序，再按源各取 PER_SOURCE_LIMIT 条，
    防止单一源霸榜（曾出现 5 条工具全来自 SkillsHub 热门、全是 20 万星以上的老项目）。
      SkillsHub → 相对增速 日增/总星（小项目高增速优先）
      GitHub    → 星/天（新建 + 涨得猛优先）
      Show HN   → 评论数（讨论最多）
    """
    rss = rss_fetcher.fetch_all(TOOL_FEEDS)
    rss.sort(key=lambda i: _skillhub_rate(i["title"]), reverse=True)
    for i in rss:
        cleaned = _clean_tool_title(i["title"])
        if cleaned != i["title"]:
            i["summary"] = f"{i['title']}。{i['summary']}"  # 排名/星数/增速留给 LLM 当素材
            i["title"] = cleaned

    out, counts = [], {}
    for item in rss + fetch_github() + fetch_showhn():
        if counts.get(item["source"], 0) >= PER_SOURCE_LIMIT:
            continue
        counts[item["source"]] = counts.get(item["source"], 0) + 1
        out.append(item)
    print(f"[INFO] 工具候选合计 {len(out)} 条（每源上限 {PER_SOURCE_LIMIT}）")
    return out
