import hashlib
import json
import os
from datetime import datetime, timedelta, timezone

import httpx

from .models import Metrics


class CollectionError(Exception):
    def __init__(self, message, retryable=False):
        super().__init__(message)
        self.retryable = retryable


def scope_key(config):
    """A changed endpoint, field mapping or filter must not reuse old baselines."""
    identity = {
        "scope": config["site"]["scope"],
        "url": config["site"]["base_url"],
        "endpoint": config["site"]["metrics_path"],
        "query": config["query"],
        "fields": config["fields"],
    }
    digest = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()[:16]
    return f"{config['site']['scope']}:{digest}"


def normalize(payload, config, start, end):
    if not isinstance(payload, dict):
        raise CollectionError("接口响应必须为 JSON 对象")
    if payload.get("success") is False:
        raise CollectionError("后台返回业务失败；请核对权限和接口")
    values = {}
    try:
        for name in ("total", "success", "failure", "p50_seconds", "p95_seconds", "latency_samples"):
            path = config["fields"].get(name)
            if path:
                value = payload
                for key in path.split("."):
                    value = value[key]
                values[name] = value
        site = config["site"]
        return Metrics(site_id=site["id"], site_name=site["name"], source=site["source"],
                       scope=scope_key(config), start=start, end=end,
                       window_kind=config["query"].get("mode", "absolute"), **values)
    except (KeyError, TypeError, ValueError) as exc:
        raise CollectionError("数据字段缺失或统计口径无效；请核对字段映射及接口响应") from exc


def collect(config, start, end, client=None):
    token = os.environ.get("AUTOLYCUS_ACCESS_TOKEN", "").strip()
    if not token:
        raise CollectionError("未设置 AUTOLYCUS_ACCESS_TOKEN")
    site, query = config["site"], config["query"]
    if "replace-with" in site["metrics_path"] or site["base_url"].endswith("example.com"):
        raise CollectionError("请先配置真实且已确认的聚合统计接口")
    headers = {"Authorization": f"Bearer {token}"}
    if user_id := os.environ.get("AUTOLYCUS_USER_ID"):
        headers["New-Api-User"] = user_id
    params = dict(query.get("filters", {}))
    relative = query.get("mode", "absolute") == "relative"
    if relative:
        params["range"] = query.get("range", "1h")
    else:
        params.update({query["start_parameter"]: int(start.timestamp()), query["end_parameter"]: int(end.timestamp())})
    def request(active_client):
        # Relative API does not expose exact server window bounds. Label these
        # local request-time bounds as estimates, never as a fixed-hour query.
        observed_end = datetime.now(timezone(timedelta(hours=8))).replace(microsecond=0) if relative else end
        observed_start = observed_end - timedelta(hours=1) if relative else start
        try:
            response = active_client.get(site["base_url"].rstrip("/") + site["metrics_path"],
                                         params=params, headers=headers, timeout=site.get("timeout_seconds", 20))
            response.raise_for_status()
            payload = response.json()
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            raise CollectionError(f"后台 HTTP 错误：{status}", retryable=status in (408, 429) or status >= 500) from None
        except httpx.RequestError:
            raise CollectionError("后台网络请求失败", retryable=True) from None
        except ValueError:
            raise CollectionError("后台响应不是有效 JSON") from None
        return normalize(payload, config, observed_start, observed_end)
    if client is not None:
        return request(client)
    with httpx.Client(follow_redirects=False) as active_client:
        return request(active_client)
