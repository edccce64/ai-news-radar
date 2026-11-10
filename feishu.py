import base64
import hashlib
import hmac
import json
import os
import time

import requests

from config import CARD_MAX_BYTES, CARD_SEND_INTERVAL

TIMEOUT = 15
# 整点高压限流（官方建议避开整点半点）；北京 9:00 恰是整点，可能撞上
RATE_LIMIT_CODE = 11232
RATE_LIMIT_WAIT = 30

# 单个字段的长度上限。LLM 不一定守 prompt 的字数限制，一条超长就能把整卡顶过
# 18KB 拆卡线，而拆卡救不了「单条本身超限」——只能截断。
MAX_SUMMARY_CHARS = 700
MAX_ANSWER_CHARS = 200


def _sign(timestamp, secret):
    """飞书加签：key 为 "{timestamp}\n{secret}"，message 为空串。"""
    key = f"{timestamp}\n{secret}".encode()
    return base64.b64encode(hmac.new(key, digestmod=hashlib.sha256).digest()).decode("utf-8")


def _stars(n):
    """n 颗实心星 + (5-n) 颗空心星。"""
    return "★" * n + "☆" * (5 - n)


def _clip(text, limit):
    """按上限截断字段。超长说明模型没守字数限制，宁可截断也不能让整卡超限。"""
    s = str(text or "")
    return s if len(s) <= limit else s[:limit] + "…"


def _panel(entry):
    """一条目 → 一个折叠面板：标题常驻，正文折叠。"""
    a = entry["analysis"]
    body = (
        f"**原文**：[{entry['link']}]({entry['link']})\n\n"
        f"**摘要**\n{_clip(a['摘要'], MAX_SUMMARY_CHARS)}\n\n"
        f"**普通人影响**\n{_clip(a['普通人影响'], MAX_ANSWER_CHARS)}\n\n"
        f"**自媒体选题**\n{_clip(a['自媒体选题'], MAX_ANSWER_CHARS)}\n\n"
        f"**快速上手**\n{_clip(a['快速上手'], MAX_ANSWER_CHARS)}"
    )
    return {
        "tag": "collapsible_panel",
        "expanded": False,
        "header": {
            "title": {
                "tag": "markdown",
                "content": f"{_stars(entry['stars'])} {entry['title']}（{entry['source']}）",
            },
            "vertical_align": "center",
            "icon": {
                "tag": "standard_icon",
                "token": "down-small-ccm_outlined",
                "size": "16px 16px",
            },
            "icon_position": "right",
            "icon_expanded_angle": -180,
        },
        "border": {"color": "grey", "corner_radius": "5px"},
        "vertical_spacing": "8px",
        "padding": "8px 8px 8px 8px",
        "elements": [{"tag": "markdown", "content": body}],
    }


def _payload(title, panels):
    """组装一张交互卡片的请求体。"""
    return {
        "msg_type": "interactive",
        "card": {
            "schema": "2.0",
            "config": {"update_multi": True},
            "header": {
                "title": {"tag": "plain_text", "content": title},
                "template": "blue",
            },
            "body": {"elements": panels},
        },
    }


def _size(payload):
    """请求体的 UTF-8 字节数。飞书按字节算上限，不是字符数。"""
    return len(json.dumps(payload, ensure_ascii=False).encode("utf-8"))


SECTION_NEWS = "**📰 今日要闻**"
SECTION_TOOLS = "**🛠 工具与 Skill**"
EMPTY_NEWS = "今日无新增要闻"
EMPTY_TOOLS = "今日无新增优质工具"


def _md(text) -> dict:
    return {"tag": "markdown", "content": text}


def _section_head(section, continued=False) -> dict:
    """区标题元素。续卡加「（续）」，免得读者把两张卡的同名区当成重复推送。"""
    text = section.strip("*").strip()
    if continued:
        text += "（续）"
    return _md(f"**{text}**")


def _pack_section(title, section, entries) -> list[tuple[list[dict], list[dict]]]:
    """把一个区的条目按 CARD_MAX_BYTES 打包成若干 (元素列表, 条目列表)。

    每张卡都从该区标题开始——单独转发某一张卡时也能看懂它属于哪个区。
    单条自身就超限时仍单独成卡，靠 _panel 的字段截断兜底（拆卡救不了「单条超限」）。
    """
    groups: list[tuple[list[dict], list[dict]]] = []
    current, current_entries = [], []
    for e in entries:
        elem = _panel(e)
        if current and _size(_payload(title, current + [elem])) > CARD_MAX_BYTES:
            groups.append((current, current_entries))
            current, current_entries = [], []
        current.append(elem)
        current_entries.append(e)
    if current:
        groups.append((current, current_entries))

    return [
        ([_section_head(section, continued=i > 0), *elems], ents)
        for i, (elems, ents) in enumerate(groups)
    ]


def build_cards(title, news_entries, tool_entries) -> tuple[list[dict], list[list[dict]]]:
    """两区排版：**每个区各自组卡**，一张卡里只放一个区。

    为什么不再混排后一刀切：混排切卡会把「工具与 Skill」劈到两张卡上，
    读者看到卡片 1 末尾一个区标题 + 1 条、卡片 2 又一个同名区标题 + 4 条，
    分不清是重复还是接续（2026-11-10 真实发生过）。
    按区打包后每张卡只含一个区，续卡标题带「（续）」。

    空区**不隐藏**——整块消失会让读者分不清「今天没货」和「坏了」。
    占位只有两行，塞进最后一张卡末尾或单独成卡。

    返回 (cards, card_entries)：card_entries[i] 是第 i 张卡里的条目，
    供调用方**按卡粒度**入库——某张卡发送失败时，前面已推的不丢。
    """
    groups: list[tuple[list[dict], list[dict]]] = []
    placeholders: list[dict] = []
    for section, entries, empty_text in (
        (SECTION_NEWS, news_entries, EMPTY_NEWS),
        (SECTION_TOOLS, tool_entries, EMPTY_TOOLS),
    ):
        if not entries:
            placeholders += [_section_head(section), _md(empty_text)]
            continue
        groups += _pack_section(title, section, entries)

    if not groups:
        # 两区都空：一张卡说清，不浪费两次请求
        return [_payload(title, placeholders)], [[]]

    if placeholders:
        last_elems, last_entries = groups[-1]
        if _size(_payload(title, last_elems + placeholders)) <= CARD_MAX_BYTES:
            groups[-1] = (last_elems + placeholders, last_entries)
        else:
            groups.append((placeholders, []))

    cards = [_payload(title, elems) for elems, _ in groups]

    # 多张卡时标题带序号：两张卡同名标题在飞书里翻下来仍像重复推送
    if len(cards) > 1:
        for i, card in enumerate(cards, 1):
            card["card"]["header"]["title"]["content"] = f"{title}（{i}/{len(cards)}）"

    return cards, [entries for _, entries in groups]


def _webhook_url() -> str:
    """取 webhook 地址。缺了给可读提示，而不是裸 KeyError traceback。"""
    url = os.environ.get("FEISHU_WEBHOOK_URL", "").strip()
    if not url:
        raise SystemExit("缺少环境变量 FEISHU_WEBHOOK_URL，请检查 .env 或 GitHub Secrets")
    return url


def _post(payload):
    """发一张卡片。

    **错误信息里绝不能出现 webhook URL** —— 那串 token 就是凭据，谁拿到都能往群里发消息。
    而 requests 的异常字符串自带完整 URL（`404 Client Error: ... for url: https://.../hook/<token>`），
    直接 raise_for_status() 会把凭据打进终端、Actions 日志、还有你贴给别人排错的聊天记录。
    所以这里只报异常类型名、HTTP 状态码和响应体，永远不拼 URL。
    """
    url = _webhook_url()
    try:
        resp = requests.post(url, json=payload, timeout=TIMEOUT)
    except requests.RequestException as exc:
        raise SystemExit(f"飞书请求失败：{type(exc).__name__}") from None
    if resp.status_code != 200:
        raise SystemExit(f"飞书推送失败：HTTP {resp.status_code}，{resp.text[:200]}")
    try:
        return resp.json()
    except ValueError:
        raise SystemExit(f"飞书返回非 JSON：HTTP {resp.status_code}") from None


def notify_empty(title) -> None:
    """今日无重要更新的简短通知。静默退出会让定时任务无法区分「没新闻」和「挂了」。"""
    return send_all(
        [
            {
                "msg_type": "interactive",
                "card": {
                    "schema": "2.0",
                    "config": {"update_multi": True},
                    "header": {
                        "title": {"tag": "plain_text", "content": title},
                        "template": "grey",
                    },
                    "body": {
                        "elements": [{"tag": "markdown", "content": "今日无重要更新，跳过推送。"}]
                    },
                },
            }
        ]
    )


def send_test() -> None:
    """发一条纯文本测试消息。

    用途：开飞书「签名校验」前后各跑一次，确认 webhook 与签名都通。
    带签名时飞书会校验 sign 字段，配错会报 19021（sign match fail）。
    """
    secret = os.environ.get("FEISHU_SECRET", "")
    mode = "带签名" if secret else "无签名（FEISHU_SECRET 未配置）"
    return send_all(
        [
            {
                "msg_type": "text",
                "content": {"text": f"[AI 信息情报官] 连通性测试推送成功｜签名模式：{mode}"},
            }
        ]
    )


def send_all(payloads, on_sent=None) -> None:
    """逐张发送，卡间 sleep。每张成功后回调 on_sent(i)。

    on_sent 供调用方按卡入库：发送中途失败时，前面已成功的卡不丢、
    后面未发的不入库下次重试，不会整批重复推。
    """
    secret = os.environ.get("FEISHU_SECRET", "")
    for i, payload in enumerate(payloads):
        if secret:
            timestamp = str(int(time.time()))
            payload["timestamp"] = timestamp
            payload["sign"] = _sign(timestamp, secret)

        data = _post(payload)
        if data.get("code") == RATE_LIMIT_CODE:
            print(f"[警告] 飞书高压限流，{RATE_LIMIT_WAIT}s 后重试")
            time.sleep(RATE_LIMIT_WAIT)
            data = _post(payload)
        if data.get("code", 0) != 0:
            raise SystemExit(f"飞书推送失败：{data}")

        print(f"[OK] 飞书卡片 {i + 1}/{len(payloads)}")
        if on_sent:
            on_sent(i)
        if i < len(payloads) - 1:
            time.sleep(CARD_SEND_INTERVAL)
