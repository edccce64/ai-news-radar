"""核心逻辑单测。标准库 unittest，不引入额外依赖。

跑法：
    .venv\\Scripts\\python.exe -m unittest discover -s tests -v
"""

import contextlib
import importlib.util
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

import api_fetcher  # noqa: E402
import feishu  # noqa: E402
import llm  # noqa: E402
import main  # noqa: E402
import store  # noqa: E402


def _item(title, summary="一段摘要", link="", kind="news"):
    return {"title": title, "summary": summary, "link": link or f"https://x/{title}", "kind": kind}


def _entry(title, summary="摘要", stars=5, analysis=None):
    return {
        "title": title,
        "source": "测试源",
        "link": f"https://x/{title}",
        "stars": stars,
        "analysis": analysis
        or {
            "质量": 4,
            "摘要": summary,
            "普通人影响": "影响",
            "自媒体选题": "选题",
            "快速上手": "上手",
        },
    }


class TestExactDedup(unittest.TestCase):
    def test_same_title_different_case_is_one(self):
        items = [_item("OpenAI 发布 GPT-5"), _item("openai 发布 gpt-5")]
        self.assertEqual(len(main._exact_dedup(items)), 1)

    def test_empty_link_and_title_do_not_swallow_each_other(self):
        items = [
            {"title": "", "link": "", "summary": "", "kind": "news"},
            {"title": "", "link": "", "summary": "", "kind": "news"},
        ]
        # 空 key 不该被当成「同一条」
        self.assertEqual(len(main._exact_dedup(items)), 2)

    def test_distinct_items_kept(self):
        items = [_item("A"), _item("B")]
        self.assertEqual(len(main._exact_dedup(items)), 2)


class TestSelect(unittest.TestCase):
    def _scores(self, spec):
        return {n: s for n, s in spec.items()}

    def test_duplicate_of_ring_does_not_hang(self):
        items = [_item("一"), _item("二")]
        # 模型吐出互指的环：1->2, 2->1
        scores = self._scores(
            {
                1: {"relevant": True, "stars": 5, "duplicate_of": 2, "already_pushed": False},
                2: {"relevant": True, "stars": 4, "duplicate_of": 1, "already_pushed": False},
            }
        )
        out = main._select(items, scores, 10)
        self.assertLessEqual(len(out), 2)

    def test_already_pushed_drops_whole_group(self):
        items = [_item("主条目"), _item("重复报道")]
        scores = self._scores(
            {
                1: {"relevant": True, "stars": 5, "duplicate_of": None, "already_pushed": True},
                2: {"relevant": True, "stars": 5, "duplicate_of": 1, "already_pushed": False},
            }
        )
        self.assertEqual(main._select(items, scores, 10), [])

    def test_low_stars_filtered(self):
        items = [_item("弱条目")]
        scores = self._scores(
            {
                1: {"relevant": True, "stars": 2, "duplicate_of": None, "already_pushed": False},
            }
        )
        self.assertEqual(main._select(items, scores, 10), [])

    def test_not_relevant_filtered(self):
        items = [_item("无关")]
        scores = self._scores(
            {
                1: {"relevant": False, "stars": 5, "duplicate_of": None, "already_pushed": False},
            }
        )
        self.assertEqual(main._select(items, scores, 10), [])

    def test_sorted_by_stars_and_truncated(self):
        items = [_item("三星"), _item("五星"), _item("四星")]
        scores = self._scores(
            {
                1: {"relevant": True, "stars": 3, "duplicate_of": None, "already_pushed": False},
                2: {"relevant": True, "stars": 5, "duplicate_of": None, "already_pushed": False},
                3: {"relevant": True, "stars": 4, "duplicate_of": None, "already_pushed": False},
            }
        )
        out = main._select(items, scores, 2)
        self.assertEqual([e["title"] for e in out], ["五星", "四星"])

    def test_missing_score_entry_is_skipped(self):
        items = [_item("有分"), _item("没分")]
        scores = self._scores(
            {
                1: {"relevant": True, "stars": 5, "duplicate_of": None, "already_pushed": False},
            }
        )
        out = main._select(items, scores, 10)
        self.assertEqual(len(out), 1)


class TestParseJson(unittest.TestCase):
    def test_code_fence(self):
        raw = '```json\n[{"id": 1, "stars": 5}]\n```'
        self.assertEqual(llm._parse_json(raw)[0]["id"], 1)

    def test_surrounding_prose(self):
        raw = '好的，结果如下：[{"id": 1}] 就这样'
        parsed = llm._parse_json(raw)
        # 数组必须保持数组：变成 dict 会让 _score_map 判非法，整天报废
        self.assertIsInstance(parsed, list)
        self.assertEqual(parsed[0]["id"], 1)

    def test_prose_wrapped_multi_item_array(self):
        raw = '结果如下：[{"id": 1, "stars": 5}, {"id": 2, "stars": 4}] 完毕'
        parsed = llm._parse_json(raw)
        self.assertIsInstance(parsed, list)
        self.assertEqual(len(parsed), 2)

    def test_prose_with_bracket_noise(self):
        raw = '见 [1]：[{"id": 1, "stars": 5}]'
        parsed = llm._parse_json(raw)
        self.assertIsInstance(parsed, list)
        self.assertEqual(parsed[0]["id"], 1)

    def test_prose_wrapped_object_still_parses(self):
        raw = '只找到这一条：{"id": 1, "stars": 5}'
        self.assertEqual(llm._parse_json(raw)["id"], 1)

    def test_invalid_raises_value_error(self):
        with self.assertRaises(ValueError):
            llm._parse_json("完全不是 JSON")

    def test_error_message_is_truncated(self):
        with self.assertRaises(ValueError) as ctx:
            llm._parse_json("x" * 5000)
        self.assertLess(len(str(ctx.exception)), 1000)


class TestRedact(unittest.TestCase):
    def test_api_key_is_masked(self):
        with mock.patch.dict(os.environ, {"DEEPSEEK_API_KEY": "sk-testkey-12345678"}):
            out = llm._redact("失败：key=sk-testkey-12345678")
        self.assertNotIn("sk-testkey-12345678", out)
        self.assertIn("***", out)

    def test_short_values_not_masked(self):
        with mock.patch.dict(os.environ, {"DEEPSEEK_API_KEY": "short"}):
            out = llm._redact("值是 short")
        self.assertIn("short", out)

    def test_base_url_with_credentials_masked(self):
        with mock.patch.dict(os.environ, {"MIMO_BASE_URL": "https://u:p@host/v1"}):
            out = llm._redact("连不上 https://u:p@host/v1")
        self.assertNotIn("u:p@", out)

    def test_plain_base_url_kept(self):
        with mock.patch.dict(os.environ, {"MIMO_BASE_URL": "https://api.example.com/v1"}):
            out = llm._redact("连不上 https://api.example.com/v1")
        self.assertIn("api.example.com", out)


class TestFeishuPost(unittest.TestCase):
    """关键安全测试：飞书 webhook URL 绝不能出现在错误信息里。"""

    SECRET = "cb1f0be2-1014-496a-b3d8-c613ce79c9a8"

    def test_network_error_message_has_no_url(self):
        boom = feishu.requests.ConnectionError(
            f"Max retries exceeded with url: /open-apis/bot/v2/hook/{self.SECRET}"
        )
        with mock.patch.object(feishu.requests, "post", side_effect=boom):
            with mock.patch.dict(
                os.environ, {"FEISHU_WEBHOOK_URL": f"https://open.feishu.cn/hook/{self.SECRET}"}
            ):
                with self.assertRaises(SystemExit) as ctx:
                    feishu._post({"a": 1})
        msg = str(ctx.exception)
        self.assertNotIn(self.SECRET, msg)
        self.assertNotIn("hook/", msg)
        self.assertIn("ConnectionError", msg)

    def test_http_error_message_has_no_url(self):
        resp = mock.Mock(status_code=500, text="server error")
        with mock.patch.object(feishu.requests, "post", return_value=resp):
            with mock.patch.dict(
                os.environ, {"FEISHU_WEBHOOK_URL": f"https://open.feishu.cn/hook/{self.SECRET}"}
            ):
                with self.assertRaises(SystemExit) as ctx:
                    feishu._post({"a": 1})
        msg = str(ctx.exception)
        self.assertNotIn(self.SECRET, msg)
        self.assertIn("HTTP 500", msg)

    def test_non_json_response_message_has_no_url(self):
        resp = mock.Mock(status_code=200, text="<html>")
        resp.json.side_effect = ValueError("no json")
        with mock.patch.object(feishu.requests, "post", return_value=resp):
            with mock.patch.dict(
                os.environ, {"FEISHU_WEBHOOK_URL": f"https://open.feishu.cn/hook/{self.SECRET}"}
            ):
                with self.assertRaises(SystemExit) as ctx:
                    feishu._post({"a": 1})
        self.assertNotIn(self.SECRET, str(ctx.exception))


class TestSendAll(unittest.TestCase):
    """签名与限流链路。开启飞书「签名校验」前，这些必须先绿。"""

    def _resp(self, code=0):
        r = mock.Mock(status_code=200, text="")
        r.json.return_value = {"code": code}
        return r

    def test_sign_matches_manual_hmac(self):
        import base64
        import hashlib
        import hmac

        ts, secret = "1700000000", "abc"
        key = f"{ts}\n{secret}".encode()
        expect = base64.b64encode(hmac.new(key, digestmod=hashlib.sha256).digest()).decode("utf-8")
        self.assertEqual(feishu._sign(ts, secret), expect)

    def test_signature_added_when_secret_present(self):
        payload = {"msg_type": "interactive"}
        with mock.patch.object(feishu.requests, "post", return_value=self._resp()) as post:
            with mock.patch.dict(
                os.environ,
                {
                    "FEISHU_WEBHOOK_URL": "https://open.feishu.cn/hook/TOKEN",
                    "FEISHU_SECRET": "s3cr3t-value",
                },
            ):
                with mock.patch.object(feishu.time, "sleep"):
                    feishu.send_all([payload])
        sent = post.call_args.kwargs["json"]
        self.assertIn("timestamp", sent)
        self.assertIn("sign", sent)
        self.assertEqual(sent["sign"], feishu._sign(sent["timestamp"], "s3cr3t-value"))

    def test_no_signature_without_secret(self):
        payload = {"msg_type": "interactive"}
        with mock.patch.object(feishu.requests, "post", return_value=self._resp()) as post:
            with mock.patch.dict(
                os.environ,
                {
                    "FEISHU_WEBHOOK_URL": "https://open.feishu.cn/hook/TOKEN",
                },
                clear=False,
            ):
                os.environ.pop("FEISHU_SECRET", None)
                with mock.patch.object(feishu.time, "sleep"):
                    feishu.send_all([payload])
        sent = post.call_args.kwargs["json"]
        self.assertNotIn("sign", sent)
        self.assertNotIn("timestamp", sent)

    def test_rate_limit_code_triggers_one_retry(self):
        with mock.patch.object(
            feishu.requests, "post", side_effect=[self._resp(code=11232), self._resp()]
        ) as post:
            with mock.patch.dict(os.environ, {"FEISHU_WEBHOOK_URL": "https://x/hook/T"}):
                with mock.patch.object(feishu.time, "sleep"):
                    feishu.send_all([{"msg_type": "text"}])
        self.assertEqual(post.call_count, 2)

    def test_on_sent_called_for_each_success(self):
        sent = []
        with mock.patch.object(feishu.requests, "post", return_value=self._resp()):
            with mock.patch.dict(os.environ, {"FEISHU_WEBHOOK_URL": "https://x/hook/T"}):
                with mock.patch.object(feishu.time, "sleep"):
                    feishu.send_all(
                        [{"msg_type": "text"}, {"msg_type": "text"}],
                        on_sent=sent.append,
                    )
        self.assertEqual(sent, [0, 1])

    def test_failure_keeps_earlier_callbacks(self):
        """第二张卡失败时，第一张已入库的不该丢。"""
        ok = self._resp()
        bad = mock.Mock(status_code=200, text="")
        bad.json.return_value = {"code": 19024, "msg": "keyword not matched"}
        sent = []
        with mock.patch.object(feishu.requests, "post", side_effect=[ok, bad]):
            with mock.patch.dict(os.environ, {"FEISHU_WEBHOOK_URL": "https://x/hook/T"}):
                with mock.patch.object(feishu.time, "sleep"):
                    with self.assertRaises(SystemExit):
                        feishu.send_all(
                            [{"msg_type": "text"}, {"msg_type": "text"}],
                            on_sent=sent.append,
                        )
        self.assertEqual(sent, [0])


class TestSendTest(unittest.TestCase):
    """--test-push 的行为：只发一条纯文本，不带卡片。"""

    def _resp(self):
        r = mock.Mock(status_code=200, text="")
        r.json.return_value = {"code": 0}
        return r

    def test_reports_signature_mode(self):
        with mock.patch.object(feishu.requests, "post", return_value=self._resp()) as post:
            with mock.patch.dict(os.environ, {"FEISHU_WEBHOOK_URL": "https://x/hook/T"}):
                os.environ.pop("FEISHU_SECRET", None)
                feishu.send_test()
        sent = post.call_args.kwargs["json"]
        self.assertEqual(sent["msg_type"], "text")
        self.assertIn("无签名", sent["content"]["text"])
        self.assertNotIn("sign", sent)

    def test_signature_mode_when_secret_present(self):
        with mock.patch.object(feishu.requests, "post", return_value=self._resp()) as post:
            with mock.patch.dict(
                os.environ,
                {
                    "FEISHU_WEBHOOK_URL": "https://x/hook/T",
                    "FEISHU_SECRET": "s3cr3t-value",
                },
            ):
                feishu.send_test()
        sent = post.call_args.kwargs["json"]
        self.assertIn("带签名", sent["content"]["text"])
        self.assertIn("sign", sent)


class TestBuildCards(unittest.TestCase):
    def test_empty_sections_are_still_shown(self):
        cards, entries = feishu.build_cards("标题", [], [])
        self.assertEqual(len(cards), 1)
        body = json.dumps(cards[0], ensure_ascii=False)
        self.assertIn("今日无新增要闻", body)
        self.assertIn("今日无新增优质工具", body)
        self.assertEqual(entries[0], [])

    def test_long_content_is_split(self):
        long_summary = "字" * 1200
        news = [_entry(f"条目{i}", summary=long_summary, stars=5) for i in range(30)]
        cards, entries = feishu.build_cards("标题", news, [])
        self.assertGreater(len(cards), 1)
        for card in cards:
            self.assertLessEqual(feishu._size(card), feishu.CARD_MAX_BYTES)
        # 条目总数不能因为拆卡而丢失
        self.assertEqual(sum(len(e) for e in entries), 30)

    def test_single_oversize_entry_is_clipped(self):
        crazy = _entry("超长", summary="字" * 50000, stars=5)
        cards, _ = feishu.build_cards("标题", [crazy], [])
        self.assertLessEqual(feishu._size(cards[0]), feishu.CARD_MAX_BYTES)

    def test_section_header_restored_after_split(self):
        news = [_entry(f"条目{i}", summary="字" * 600, stars=5) for i in range(30)]
        cards, _ = feishu.build_cards("标题", news, [])
        # 后续卡仍应带「今日要闻」区标题，并标明是接续
        self.assertIn("今日要闻", json.dumps(cards[1], ensure_ascii=False))
        self.assertIn("（续）", json.dumps(cards[1], ensure_ascii=False))

    def test_news_and_tools_never_share_a_card(self):
        """2026-11-10 真实 bug：混排切卡把工具区劈成两半，出现两个「工具与 Skill」标题。"""
        news = [_entry(f"要闻{i}", summary="字" * 600) for i in range(5)]
        tools = [_entry(f"工具{i}", summary="字" * 600) for i in range(5)]
        cards, _ = feishu.build_cards("标题", news, tools)
        self.assertGreater(len(cards), 1)
        for card in cards:
            body = json.dumps(card, ensure_ascii=False)
            self.assertFalse(
                "今日要闻" in body and "工具与 Skill" in body,
                "一张卡里不该同时出现两个区",
            )

    def test_section_head_appears_once_per_section(self):
        """非续卡的区标题全卡只出现一次，不会因切卡重复。"""
        news = [_entry(f"要闻{i}", summary="字" * 600) for i in range(5)]
        tools = [_entry(f"工具{i}", summary="字" * 600) for i in range(5)]
        cards, _ = feishu.build_cards("标题", news, tools)
        bodies = [json.dumps(c, ensure_ascii=False) for c in cards]
        self.assertEqual(sum(1 for b in bodies if "**📰 今日要闻**" in b), 1)
        self.assertEqual(sum(1 for b in bodies if "**🛠 工具与 Skill**" in b), 1)

    def test_multi_card_titles_are_numbered(self):
        """多张卡时标题带序号，翻下来不会误以为重复推送。"""
        news = [_entry(f"要闻{i}", summary="字" * 600) for i in range(5)]
        tools = [_entry(f"工具{i}", summary="字" * 600) for i in range(5)]
        cards, _ = feishu.build_cards("日报", news, tools)
        self.assertGreater(len(cards), 1)
        titles = [c["card"]["header"]["title"]["content"] for c in cards]
        self.assertEqual(titles, [f"日报（{i}/{len(cards)}）" for i in range(1, len(cards) + 1)])

    def test_single_card_title_has_no_number(self):
        cards, _ = feishu.build_cards("日报", [_entry("只有一条")], [])
        self.assertEqual(cards[0]["card"]["header"]["title"]["content"], "日报")

    def test_one_section_empty_merges_placeholder(self):
        """只有要闻时，工具区的占位塞进同一张卡，不单独占一张。"""
        news = [_entry(f"要闻{i}") for i in range(2)]
        cards, entries = feishu.build_cards("标题", news, [])
        self.assertEqual(len(cards), 1)
        body = json.dumps(cards[0], ensure_ascii=False)
        self.assertIn("今日要闻", body)
        self.assertIn("今日无新增优质工具", body)
        self.assertEqual(len(entries[0]), 2)


class TestSkillhubRate(unittest.TestCase):
    def test_k_suffix(self):
        rate = api_fetcher._skillhub_rate("#5 AIHOT — ★ 4.9k (1.2k/day)")
        self.assertAlmostEqual(rate, 1200 / 4900, places=3)

    def test_m_suffix(self):
        rate = api_fetcher._skillhub_rate("#1 laya — ★ 30.2k (2.0k/day)")
        self.assertAlmostEqual(rate, 2000 / 30200, places=3)

    def test_zero_total_does_not_divide_by_zero(self):
        self.assertEqual(api_fetcher._skillhub_rate("#0 x — ★ 0 (0/day)"), 0.0)

    def test_no_match_returns_zero(self):
        self.assertEqual(api_fetcher._skillhub_rate("普通标题"), 0.0)


class TestCleanToolTitle(unittest.TestCase):
    def test_rank_and_stats_removed(self):
        self.assertEqual(api_fetcher._clean_tool_title("#5 AIHOT — ★ 4.9k (1.2k/day)"), "AIHOT")

    def test_plain_title_unchanged(self):
        self.assertEqual(api_fetcher._clean_tool_title("普通标题"), "普通标题")


class _TempDBMixin:
    """把 store.DB_PATH 指到临时目录，测试不碰真实的 data/seen.db。"""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        patcher = mock.patch.object(store, "DB_PATH", Path(tmp.name) / "seen.db")
        patcher.start()
        self.addCleanup(patcher.stop)


class TestEmptyNotice(_TempDBMixin, unittest.TestCase):
    def test_first_notice_not_recorded(self):
        self.assertFalse(store.notified_empty_today())
        store.mark_notified_empty()
        self.assertTrue(store.notified_empty_today())

    def test_mark_twice_is_idempotent(self):
        store.mark_notified_empty()
        store.mark_notified_empty()
        self.assertTrue(store.notified_empty_today())

    def test_empty_notice_does_not_finish_the_day(self):
        # 只压空通知，不能锁住当天：后面触发点拿到新条目时仍要能正常推
        store.mark_notified_empty()
        self.assertFalse(store.finished_today())


class TestEmptyNoticeOncePerDay(_TempDBMixin, unittest.TestCase):
    def test_three_triggers_send_one_notice(self):
        calls = []
        with (
            mock.patch.object(main.rss_fetcher, "fetch_all", return_value=[]),
            mock.patch.object(main.api_fetcher, "fetch_aggregator", return_value=[]),
            mock.patch.object(main.api_fetcher, "fetch_tools", return_value=[]),
            mock.patch.object(main.feishu, "notify_empty", side_effect=calls.append),
            mock.patch.object(sys, "argv", ["main.py"]),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            for _ in range(3):
                main.main()
        self.assertEqual(len(calls), 1)


def _load_notify_failure():
    path = os.path.join(_ROOT, "tools", "notify_failure.py")
    spec = importlib.util.spec_from_file_location("notify_failure", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestNotifyFailure(unittest.TestCase):
    def setUp(self):
        self.module = _load_notify_failure()

    def test_sign_matches_feishu(self):
        # 两处实现必须一致，否则正式推送带签、告警不带签，告警会被飞书拒
        self.assertEqual(
            self.module._sign("1700000000", "s3cret"),
            feishu._sign("1700000000", "s3cret"),
        )

    def test_missing_webhook_is_skipped(self):
        with (
            mock.patch.dict(os.environ, {"FEISHU_WEBHOOK_URL": ""}),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            self.assertEqual(self.module.main(), 0)


if __name__ == "__main__":
    unittest.main()
