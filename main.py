import argparse
import sys

from dotenv import load_dotenv

import api_fetcher
import feishu
import llm
import rss_fetcher
import store
from config import MAX_AI_ITEMS, MAX_NEWS, MAX_TOOLS, MIN_QUALITY, MIN_STARS


def _norm(s) -> str:
    """归一化：只留字母数字并转小写，用于同稿比对。"""
    return "".join(c for c in s.lower() if c.isalnum())


def _exact_dedup(items):
    """URL/标题归一化后精确匹配，干掉同稿转载（免费，LLM 判同事件前的第一道）。"""
    seen = set()
    out = []
    for i in items:
        # 空 key 不入集合：link 与 title 都空的条目会被归一成空串，
        # 把它们当成「同一条」会让所有空条目互相吃掉
        keys = {k for k in (_norm(i["link"]), _norm(i["title"])) if k}
        if keys & seen:
            continue
        seen |= keys
        out.append(i)
    return out


def _select(items, scores, limit):
    """去噪 + 星级门槛 + 同事件只留最优一条，按星级降序取前 limit。

    scores 里没有 duplicate_of 时（工具评分）每条自成一组，天然不去重。
    already_pushed 的条目连同指向它的重复一起丢（跨天同事件不重推）。
    """

    def root(n):
        """沿 duplicate_of 链找到组长。已推过的整组返回 0（丢弃）。"""
        seen = set()
        while True:
            s = scores.get(n) or {}
            if s.get("already_pushed"):
                return 0  # 哨兵：组长是已推过的旧事件，整组不要
            d = s.get("duplicate_of")
            # 撞到已访问过的编号 = 模型吐了环（自环/互指），就地截断，不能死循环
            if not d or d in seen:
                return n
            seen.add(n)
            n = d

    best = {}  # 组长 id -> 该组内最该留的 id
    for n in range(1, len(items) + 1):
        s = scores.get(n) or {}
        if not s.get("relevant") or s.get("already_pushed"):
            continue
        r = root(n)
        if not r:
            continue
        cur = best.get(r)
        # 先比星级，并列取摘要更长的（信息更全）
        if cur is None or (s["stars"], len(items[n - 1]["summary"])) > (
            scores[cur]["stars"],
            len(items[cur - 1]["summary"]),
        ):
            best[r] = n

    out = []
    for n in best.values():
        s = scores[n]
        if s["stars"] < MIN_STARS:
            continue
        entry = dict(items[n - 1])
        entry["stars"] = s["stars"]
        out.append(entry)

    # 多的不入库，下次还能选中
    out.sort(key=lambda e: (-e["stars"], -len(e["summary"])))
    return out[:limit]


def _notify_empty_once(title) -> None:
    """空通知每天只发一次。

    三个定时点都会各跑一遍。不发过就不拦，同一张「今日无重要更新」会连发三次
    （2026-11-10 实测）。只记空通知、不写完成标记——后面触发点拿到新条目时仍可正常推。
    """
    if store.notified_empty_today():
        print("[INFO] 今日已发过空通知，跳过")
        return
    feishu.notify_empty(title)
    store.mark_notified_empty()


def main() -> None:
    """编排全流程。--dry-run 只打印，不推送、不写库。"""
    load_dotenv()

    # 本地控制台是 GBK（cp936），RSS 标题/摘要里带 emoji 或生僻字会直接
    # UnicodeEncodeError 崩掉 --dry-run。改成不可编码字符替换而不是报错。
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="跑完 RSS + LLM 后打印，不推送、不写库",
    )
    parser.add_argument(
        "--test-push",
        action="store_true",
        help="只发一条测试消息到飞书群（验证 webhook 与签名），不抓取、不写库",
    )
    args = parser.parse_args()

    if args.test_push:
        feishu.send_test()
        print("[OK] 测试消息已发送")
        return

    # 每日只推一次：schedule 延迟能到 6 小时以上，谁先跑谁推，后来的直接退出。
    # 放在抓取前，省掉 RSS/LLM 开销。--dry-run 不受影响（本地要看加工结果）。
    if not args.dry_run and store.finished_today():
        print("[INFO] 今日已推送过，跳过（每日只推一次）")
        return

    # 要闻：中文 RSS 源 + AI 聚合（80+ 源）+ 同事件聚拢
    news = _exact_dedup(
        store.filter_unpushed(rss_fetcher.fetch_all() + api_fetcher.fetch_aggregator())
    )
    # 工具与 Skill：agent-skills-hub RSS + GitHub + Show HN（天然唯一，不去重）
    tools = store.filter_unpushed(api_fetcher.fetch_tools())

    # 跨区去重：同一条目不应既进要闻区又进工具区
    tool_links = {t["link"] for t in tools}
    news = [n for n in news if n["link"] not in tool_links]

    # 每日 AI 预算：超出只抓取不加工，防止 TOP_N 调大或源变多导致成本失控。
    # 两区各占一半：原先「新闻吃满、工具拿剩余」会在 news ≥ 预算时把工具区挤成 0。
    total = len(news) + len(tools)
    if total > MAX_AI_ITEMS:
        print(f"[警告] 候选 {total} 条超每日预算 {MAX_AI_ITEMS}，两区各取前 {MAX_AI_ITEMS // 2} 条")
        news = news[: MAX_AI_ITEMS // 2]
        tools = tools[: MAX_AI_ITEMS // 2]

    print(f"[INFO] 候选：要闻 {len(news)} 条，工具与 Skill {len(tools)} 条")
    title = f"AI 情报日报 {store.today_bj()}"

    if not news and not tools:
        print("[INFO] 无新条目")
        if not args.dry_run:
            _notify_empty_once(title)
        return

    picked = []
    if news:
        picked += _select(news, llm.score_and_dedup(news, store.recent_pushed()), MAX_NEWS)
    if tools:
        picked += _select(tools, llm.score_tools(tools), MAX_TOOLS)

    # 逐条加工：skip 或低质量的直接丢弃，不硬凑
    kept = []
    for e in picked:
        a = llm.enrich(e)
        if a is None:
            continue
        if a.get("skip"):
            print(f"[跳过] 「{e['title'][:32]}」{a.get('原因', '')}")
            continue
        if a.get("质量", 0) < MIN_QUALITY:
            print(f"[跳过] 「{e['title'][:32]}」质量 {a.get('质量')} 分 < {MIN_QUALITY}")
            continue
        e["analysis"] = a
        kept.append(e)

    news_entries = [e for e in kept if e["kind"] == "news"]
    tool_entries = [e for e in kept if e["kind"] == "tool"]
    print(f"[INFO] 入选：要闻 {len(news_entries)} 条，工具与 Skill {len(tool_entries)} 条")

    if not kept:
        print("[INFO] 无入选条目")
        if not args.dry_run:
            _notify_empty_once(title)
        return

    if args.dry_run:
        for heading, group in (("【今日要闻】", news_entries), ("【工具与 Skill】", tool_entries)):
            if not group:
                continue
            print(f"\n{'#' * 60}\n# {heading}\n{'#' * 60}")
            for e in group:
                a = e["analysis"]
                print(f"\n{'=' * 60}")
                print(f"{e['title']}（{e['source']}）{'★' * e['stars']} 质量 {a['质量']}")
                print(e["link"])
                for k in ("摘要", "普通人影响", "自媒体选题", "快速上手"):
                    print(f"\n【{k}】{a[k]}")
        return

    cards, card_entries = feishu.build_cards(title, news_entries, tool_entries)
    # 按卡入库：某张失败时前面已推的不丢，后面未发的下次重试（闸门看的是完成标记，
    # 不是「今天推过没有」，所以中途失败当天仍能补发剩余卡）
    feishu.send_all(cards, on_sent=lambda i: store.mark_pushed(card_entries[i]))
    store.mark_finished()
    print(f"[OK] 已推送 {len(kept)} 条并写入 SQLite")


if __name__ == "__main__":
    main()
