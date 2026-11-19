import base64
import hashlib
import hmac
import os
import re
import time
from urllib.parse import urlsplit

import httpx
from .markdown import table_count


class NotificationError(Exception):
    def __init__(self, message, retryable=False):
        super().__init__(message)
        self.retryable = retryable


def send(text, client=None):
    webhook = os.environ.get("AUTOLYCUS_FEISHU_WEBHOOK", "")
    url = urlsplit(webhook)
    if (url.scheme != "https" or url.hostname != "open.feishu.cn" or url.port not in (None, 443)
            or url.username or url.password or not url.path.startswith("/open-apis/bot/v2/hook/")
            or url.query or url.fragment):
        raise NotificationError("请设置有效的飞书自定义机器人 HTTPS Webhook")
    if table_count(text) > 4:
        raise NotificationError("飞书单个 Markdown 组件最多支持4张表格；当前报告超限，请合并表格或生成新版报告")
    payload = {
        "msg_type": "interactive",
        "card": {
            "schema": "2.0",
            "config": {"update_multi": True},
            "body": {"elements": [{"tag": "markdown", "content": text}]},
        },
    }
    if secret := os.environ.get("AUTOLYCUS_FEISHU_SECRET"):
        timestamp = str(int(time.time()))
        signature = hmac.new(f"{timestamp}\n{secret}".encode(), b"", hashlib.sha256).digest()
        payload.update(timestamp=timestamp, sign=base64.b64encode(signature).decode())
    def request(active_client):
        try:
            response = active_client.post(webhook, json=payload, timeout=15)
            response.raise_for_status()
            result = response.json()
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            raise NotificationError(f"飞书 HTTP 错误：{status}", retryable=status in (408, 429) or status >= 500) from None
        except httpx.RequestError:
            raise NotificationError("飞书网络请求失败（投递结果可能不确定）", retryable=True) from None
        except ValueError:
            raise NotificationError("飞书响应格式错误") from None
        if not isinstance(result, dict) or type(result.get("code")) is not int or result["code"] != 0:
            # Only report numeric codes, never upstream bodies/URLs/secrets.
            code = result.get("code") if isinstance(result, dict) else None
            code = code if type(code) is int else "未知"
            match = re.search(r"ErrCode:\s*(\d{1,9})\b", str(result.get("msg", ""))) if isinstance(result, dict) else None
            detail = f"，子错误码：{match[1]}" if match else ""
            reason = "：卡片表格数量超过平台限制" if match and match[1] == "11310" else "，请按错误码核对卡片内容或机器人配置"
            raise NotificationError(f"飞书返回业务失败（错误码：{code}{detail}）{reason}")
    if client is not None:
        request(client)
    else:
        with httpx.Client(follow_redirects=False) as active_client:
            request(active_client)
