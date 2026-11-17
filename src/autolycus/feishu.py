import base64
import hashlib
import hmac
import os
import time
from urllib.parse import urlsplit

import httpx


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
    payload = {"msg_type": "text", "content": {"text": text}}
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
            raise NotificationError("飞书返回业务失败，请检查机器人安全设置")
    if client is not None:
        request(client)
    else:
        with httpx.Client(follow_redirects=False) as active_client:
            request(active_client)
