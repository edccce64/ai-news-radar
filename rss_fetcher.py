import calendar
import time

import feedparser
import requests

from config import PUBDATE_DAYS, RSS_FEEDS, TOP_N

# 部分站点不给浏览器 UA 就返回 403 或 HTML
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)
TIMEOUT = 15
SUMMARY_MAX = 200


def _clean(text) -> str:
    """压掉多余空白。"""
    return " ".join(text.split())


def _is_recent(entry):
    """只留 PUBDATE_DAYS 天内发布的。无时间戳的放行（丢条目比多推一条更糟）。"""
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    if not parsed:
        return True
    age_days = (time.time() - calendar.timegm(parsed)) / 86400
    return age_days <= PUBDATE_DAYS


def _fetch_text(url):
    """取回 feed 文本。RSSHub 镜像偶发 503/超时，失败隔几秒重试一次常能恢复。"""
    for attempt in (1, 2):
        try:
            resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT)
            resp.raise_for_status()
            return resp.text
        except Exception:
            if attempt == 2:
                raise
            time.sleep(3)


def fetch_all(feeds=None) -> list[dict]:
    """返回 [{source, title, link, summary, kind}, ...]。

    每源取窗口内最新 TOP_N 条。单源失败跳过。
    """
    feeds = RSS_FEEDS if feeds is None else feeds
    items = []
    for feed in feeds:
        try:
            entries = feedparser.parse(_fetch_text(feed["url"])).entries
        except Exception as exc:
            print(f"[警告] {feed['name']} 抓取失败，跳过：{exc}")
            continue

        # 工具/资源不看新鲜度（SkillsHub 热门榜的 pubDate 往往不是「新不新」），只看有没有价值
        top_n = feed.get("top_n", TOP_N)
        if feed.get("kind") == "tool":
            fresh = entries[:top_n]
        else:
            fresh = [e for e in entries if _is_recent(e)][:top_n]
        if not fresh:
            print(f"[警告] {feed['name']} 近 {PUBDATE_DAYS} 天无条目，跳过")
            continue

        for entry in fresh:
            items.append(
                {
                    "source": feed["name"],
                    "title": _clean(entry.get("title", "(无标题)")),
                    "link": entry.get("link", ""),
                    "summary": _clean(entry.get("summary", ""))[:SUMMARY_MAX],
                    "kind": feed.get("kind", "news"),
                }
            )
        print(f"[OK] {feed['name']}: {len(fresh)} 条")

    return items
