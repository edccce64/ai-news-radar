import datetime
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "data" / "seen.db"


def _now():
    """统一用 UTC 存时间。本地跑是北京时间、Actions 跑是 UTC，
    混用会让 pushed_within 的区间比较算错。"""
    return (
        datetime.datetime.now(datetime.timezone.utc)
        .replace(tzinfo=None)
        .isoformat(timespec="seconds")
    )


def _connect():
    """连接 SQLite 并确保表结构存在。"""
    DB_PATH.parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """CREATE TABLE IF NOT EXISTS pushed (
               link      TEXT PRIMARY KEY,
               title     TEXT NOT NULL,
               source    TEXT,
               stars     INTEGER,
               pushed_at TEXT NOT NULL
           )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS runs (
               day         TEXT PRIMARY KEY,
               finished_at TEXT NOT NULL
           )"""
    )
    # 空通知单独记：它不进 pushed，也不该锁住当天（后面触发点还可能拿到新条目）
    conn.execute(
        """CREATE TABLE IF NOT EXISTS empty_notices (
               day     TEXT PRIMARY KEY,
               sent_at TEXT NOT NULL
           )"""
    )
    return conn


def filter_unpushed(items) -> list[dict]:
    """剔除 link 已推送过的条目。"""
    conn = _connect()
    try:
        seen = {row[0] for row in conn.execute("SELECT link FROM pushed")}
    finally:
        conn.close()
    return [i for i in items if i["link"] not in seen]


def mark_pushed(entries) -> None:
    """记录已推送。entries 需含 link / title，可含 source / stars。"""
    now = _now()
    conn = _connect()
    try:
        conn.executemany(
            "INSERT OR IGNORE INTO pushed "
            "(link, title, source, stars, pushed_at) VALUES (?, ?, ?, ?, ?)",
            [(e["link"], e["title"], e.get("source", ""), e.get("stars"), now) for e in entries],
        )
        conn.commit()
    finally:
        conn.close()


def pushed_within(hours=12) -> bool:
    """最近 N 小时内推过真实条目吗？不含空通知。

    只作查询用：每日闸门是 finished_today()，空通知去重是 empty_notices 表。
    """
    cutoff = (
        datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
        - datetime.timedelta(hours=hours)
    ).isoformat(timespec="seconds")
    conn = _connect()
    try:
        row = conn.execute("SELECT COUNT(*) FROM pushed WHERE pushed_at >= ?", (cutoff,)).fetchone()
        return row[0] > 0
    finally:
        conn.close()


def today_bj():
    """北京自然日（YYYY-MM-DD），跑批的日期基准。

    必须按北京自然日，不能用滑动 N 小时：schedule 能延迟 6 小时以上，
    若某天推到晚上，滑动窗口会误拦次日早上的正常推送。

    公开函数：卡片标题的日期与完成标记必须用同一个基准，
    否则深夜手动触发会出现「标题写昨天、标记记今天」。
    """
    now_bj = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=8)
    return now_bj.date().isoformat()


def finished_today() -> bool:
    """今天（北京时间）的日报是否**完整发完**了？每日只推一次的节流 gate。

    不能用「今天推过条目没有」当闸门：多卡推送中途失败时，前面成功的卡已入库，
    闸门会锁住当天所有后续触发（三个 cron + 手动），剩下未发出的卡就永远漏发了。
    """
    conn = _connect()
    try:
        row = conn.execute("SELECT COUNT(*) FROM runs WHERE day = ?", (today_bj(),)).fetchone()
    finally:
        conn.close()
    return row[0] > 0


def mark_finished() -> None:
    """全部卡片推送成功后调用，写当日完成标记。"""
    conn = _connect()
    try:
        conn.execute(
            "INSERT OR IGNORE INTO runs (day, finished_at) VALUES (?, ?)",
            (today_bj(), _now()),
        )
        conn.commit()
    finally:
        conn.close()


def notified_empty_today() -> bool:
    """今天是否已发过「今日无重要更新」通知。"""
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT COUNT(*) FROM empty_notices WHERE day = ?", (today_bj(),)
        ).fetchone()
    finally:
        conn.close()
    return row[0] > 0


def mark_notified_empty() -> None:
    """记录今天已发过空通知。不写 runs 表：不能锁住当天后续的真实推送。"""
    conn = _connect()
    try:
        conn.execute(
            "INSERT OR IGNORE INTO empty_notices (day, sent_at) VALUES (?, ?)",
            (today_bj(), _now()),
        )
        conn.commit()
    finally:
        conn.close()


def recent_pushed(days=3, limit=50) -> list[dict]:
    """最近 N 天已推标题，供 LLM 判「是否同一件事已推过」。

    跨天同事件重复的唯一防线：filter_unpushed 只认 link，LLM 的 duplicate_of
    只在单次 run 内聚类——「36Kr 推完新智元又推」就靠这个拦。N 天与
    PUBDATE_DAYS 匹配（候选只会是窗口内的，能重复的也只有最近推过的）。
    """
    cutoff = (
        datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
        - datetime.timedelta(days=days)
    ).isoformat(timespec="seconds")
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT title, source FROM pushed WHERE pushed_at >= ? ORDER BY pushed_at DESC LIMIT ?",
            (cutoff, limit),
        ).fetchall()
    finally:
        conn.close()
    return [{"title": t, "source": s} for t, s in rows]
