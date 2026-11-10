"""Actions 跑挂时往飞书群发一条告警。

只用标准库：`pip install` 那步失败时，这个脚本仍要能跑起来。

用法：
    python tools/notify_failure.py <run_url>

环境变量：
    FEISHU_WEBHOOK_URL  必需
    FEISHU_SECRET       可选。机器人开了「签名校验」就必须填，
                        否则飞书会拒收（19021）。此前的 curl 版本没加签，
                        开了签名后告警是静默失效的。
"""

import base64
import hashlib
import hmac
import json
import os
import sys
import time
from urllib import request


def _sign(timestamp, secret):
    """与 feishu._sign 保持一致：key 为 "{timestamp}\\n{secret}"，message 为空串。"""
    key = f"{timestamp}\n{secret}".encode()
    return base64.b64encode(hmac.new(key, digestmod=hashlib.sha256).digest()).decode("utf-8")


def main() -> int:
    url = os.environ.get("FEISHU_WEBHOOK_URL", "").strip()
    if not url:
        print("未配置 FEISHU_WEBHOOK_URL，跳过失败告警")
        return 0

    run_url = sys.argv[1] if len(sys.argv) > 1 else ""
    payload = {
        "msg_type": "text",
        "content": {"text": f"⚠️ AI 情报官今日抓取失败，请检查：{run_url}"},
    }

    secret = os.environ.get("FEISHU_SECRET", "").strip()
    if secret:
        timestamp = str(int(time.time()))
        payload["timestamp"] = timestamp
        payload["sign"] = _sign(timestamp, secret)

    req = request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    # 告警失败不能盖住原始失败信息，也不打印 URL（URL 里就是凭据）
    try:
        with request.urlopen(req, timeout=15) as resp:
            body = resp.read().decode("utf-8", "replace")
    except Exception as exc:
        print(f"失败告警发送失败：{type(exc).__name__}")
        return 0

    try:
        code = json.loads(body).get("code", 0)
    except ValueError:
        code = 0
    if code != 0:
        print(f"失败告警被飞书拒绝：code={code}（签名校验是否配置了 FEISHU_SECRET？）")
    else:
        print("失败告警已发送")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
