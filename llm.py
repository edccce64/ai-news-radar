import json
import os
import time

from openai import OpenAI

from config import (
    DEEPSEEK_BASE_URL,
    DEEPSEEK_MODEL,
    ENRICH_PROMPT,
    LLM_BACKOFF_BASE,
    LLM_RETRIES,
    SCORE_PROMPT,
    THREE_QUESTIONS,
    TOOL_SCORE_PROMPT,
)

TIMEOUT = 60

# 打印异常前要脱敏的 env：API key 与签名 secret 是凭据；
# MIMO_BASE_URL 是用户自填的，万一写成 https://user:token@host 会把凭据带出来。
_SECRET_ENV = ("DEEPSEEK_API_KEY", "MIMO_API_KEY", "FEISHU_SECRET")


def _redact(text):
    """把环境变量里的敏感值从文本里抹掉，避免随异常进日志。"""
    s = str(text)
    for name in _SECRET_ENV:
        val = os.environ.get(name, "")
        if len(val) >= 8:
            s = s.replace(val, "***")
    base = os.environ.get("MIMO_BASE_URL", "")
    # 只在 URL 内嵌了 user:pass@ 时才脱敏，正常 base_url 保留，方便排查
    if len(base) >= 8 and "@" in base:
        s = s.replace(base, "***")
    return s


def _get_client_and_model():
    """按 LLM_PROVIDER 造 client 与模型名。"""
    provider = os.environ.get("LLM_PROVIDER", "").strip().lower()
    if provider == "deepseek":
        return (
            OpenAI(api_key=_need_key("DEEPSEEK_API_KEY"), base_url=DEEPSEEK_BASE_URL),
            DEEPSEEK_MODEL,
        )
    if provider == "mimo":
        return (
            OpenAI(
                api_key=_need_key("MIMO_API_KEY"),
                base_url=_need_key("MIMO_BASE_URL"),
            ),
            _need_key("MIMO_MODEL"),
        )
    raise SystemExit(f"未知 LLM_PROVIDER: {provider or '(未设置)'}（支持 deepseek / mimo）")


def _need_key(name):
    """取一个必需的环境变量，缺了给可读提示而不是裸 KeyError。"""
    val = os.environ.get(name, "").strip()
    if not val:
        raise SystemExit(f"缺少环境变量 {name}，请检查 .env")
    return val


def _chat(prompt):
    """LLM 调用，指数退避重试。单次抖动不该让整天日报报废。"""
    client, model = _get_client_and_model()
    provider = os.environ.get("LLM_PROVIDER", "?")
    last = None
    for attempt in range(1, LLM_RETRIES + 1):
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0,  # 评分/判断类任务要可复现
                seed=42,  # MoE 模型温度 0 仍有底层抖动，补 seed
                timeout=TIMEOUT,
            )
            return resp.choices[0].message.content
        except Exception as exc:
            # 鉴权失败重试没有意义：key 错了再试三次也是同样结果，还白等 2s+4s
            status = getattr(exc, "status_code", None)
            if status in (401, 403):
                raise SystemExit(
                    f"LLM 鉴权失败（HTTP {status}）：检查 {provider} 的 API Key 是否正确"
                ) from None
            last = exc
            if attempt == LLM_RETRIES:
                break
            wait = LLM_BACKOFF_BASE * (2 ** (attempt - 1))
            print(
                f"[警告] LLM 调用失败（第 {attempt}/{LLM_RETRIES} 次），{wait}s 后重试："
                f"{type(exc).__name__} {_redact(exc)}"
            )
            time.sleep(wait)
    raise SystemExit(f"LLM 调用连续 {LLM_RETRIES} 次失败：{type(last).__name__} {_redact(last)}")


def _extract_json_candidates(text):
    """从夹杂说明文字的输出里抠出候选 JSON 片段，**数组优先**。

    评分结果是数组。若先按 `{...}` 抠，`[{"a":1}]` 会被抠成 `{"a":1}`，
    数组退化成对象，_score_map 判非法后整天报废。说明文字里也常带 `[1]`
    这类方括号，所以从靠后的左括号往回试，第一个能解析的就是真 JSON。
    """
    out = []
    for open_ch, close_ch in (("[", "]"), ("{", "}")):
        end = text.rfind(close_ch)
        if end == -1:
            continue
        starts, i = [], text.find(open_ch)
        while i != -1 and i < end and len(starts) < 5:
            starts.append(i)
            i = text.find(open_ch, i + 1)
        out.extend(text[s : end + 1] for s in reversed(starts))
    return out


def _parse_json(text):
    """剥围栏 → json.loads → 失败则抠出 JSON 片段再试。都失败抛 ValueError。"""
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    for candidate in [stripped, *_extract_json_candidates(stripped)]:
        if candidate:
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                pass
    # 只留前 500 字：整段 LLM 输出进异常会让日志爆长
    raise ValueError(f"LLM 输出不是合法 JSON：\n{text[:500]}")


def _items_block(items) -> str:
    """把候选条目拼成 prompt 里的编号列表。"""
    return "\n".join(
        f"[{n}] {i['title']} | {i['source']} | {i['summary']}" for n, i in enumerate(items, 1)
    )


def _pushed_block(pushed) -> str:
    """把已推条目拼成 prompt 里的清单。"""
    return "\n".join(f"- {p['title']}（{p['source']}）" for p in pushed) or "（无）"


def _score_map(raw, total):
    """把 LLM 返回的评分数组收敛成 {id: {...}}，畸形条目直接丢。

    必须严校验：评分是几十条的大数组，逼近输出上限，模型会漏字段、吐字符串型
    "false"/"5"、甚至整体返回对象。放过去的脏数据会让 main._select 的比较与真值判断
    炸掉整轮（此前这里是裸 {r["id"]: r}，一个缺字段就 KeyError 全天报废）。
    丢弃的条目在 _select 里 scores.get(n) or {} 拿不到，自然不入选。
    """
    if not isinstance(raw, list):
        raise ValueError(f"评分结果不是数组（{type(raw).__name__}）")
    out = {}
    for r in raw:
        if not isinstance(r, dict):
            continue
        i, relevant, stars = r.get("id"), r.get("relevant"), r.get("stars")
        if not isinstance(i, int) or not 1 <= i <= total:
            continue
        if not isinstance(relevant, bool) or not isinstance(stars, int) or not 1 <= stars <= 5:
            continue
        out[i] = r
    if len(out) < total:
        print(f"[警告] 评分覆盖 {len(out)}/{total} 条，未覆盖的条目本次不入选")
    return out


def _ask_scores(prompt, total):
    """取一次评分结果。JSON 解析失败重试一次——输出畸形不代表接口调用失败。"""
    for attempt in (1, 2):
        try:
            return _score_map(_parse_json(_chat(prompt)), total)
        except ValueError as exc:
            print(f"[警告] 评分解析失败（第 {attempt}/2 次）：{exc}")
    raise SystemExit("评分连续两次返回非法 JSON，放弃今日推送")


def score_and_dedup(items, pushed=None) -> dict:
    """一次 LLM 调用完成去噪 + 星级评分 + 同事件判重（含跨天已推判重）。

    pushed 为最近已推条目（store.recent_pushed()），用于 already_pushed 判断。
    返回 {id: {"id", "relevant", "stars", "duplicate_of", "already_pushed"}}，
    id 从 1 开始对应 items 顺序。
    """
    return _ask_scores(
        SCORE_PROMPT.format(
            n=len(items),
            items_block=_items_block(items),
            pushed_block=_pushed_block(pushed or []),
        ),
        len(items),
    )


def score_tools(items) -> dict:
    """工具/Skill 条目评分，**不判重**（不同仓库/产品天然唯一）。返回 {id: {...}}。"""
    return _ask_scores(
        TOOL_SCORE_PROMPT.format(n=len(items), items_block=_items_block(items)),
        len(items),
    )


def enrich(item) -> dict | None:
    """逐条加工。

    返回 {"质量", "摘要", "普通人影响", "自媒体选题", "快速上手"}；
    素材过薄返回 {"skip": True, "原因": ...}；
    解析失败或缺字段返回 None —— 调用方跳过该条，**不炸整个流程**。
    """
    questions_block = "\n".join(f"{n}. {q}" for n, q in enumerate(THREE_QUESTIONS, 1))
    try:
        raw = _chat(
            ENRICH_PROMPT.format(
                title=item["title"],
                source=item["source"],
                link=item["link"],
                summary=item["summary"],
                questions_block=questions_block,
            )
        )
    except SystemExit as exc:
        # 单条加工失败不能带走整天：前面的条目已加工完，不该跟着一起报废
        print(f"[警告] 「{item['title'][:30]}」加工失败，跳过：{exc}")
        return None
    try:
        parsed = _parse_json(raw)
    except ValueError as exc:
        print(f"[警告] 「{item['title'][:30]}」解析失败，跳过：{exc}")
        return None

    # 严格判 True：模型偶尔吐字符串 "false"，真值判断会把它当成 skip 误丢好条目
    if parsed.get("skip") is True:
        return {"skip": True, "原因": parsed.get("原因", "")}

    missing = [
        k for k in ("质量", "摘要", "普通人影响", "自媒体选题", "快速上手") if k not in parsed
    ]
    if missing:
        print(f"[警告] 「{item['title'][:30]}」缺字段 {missing}，跳过")
        return None
    return parsed
