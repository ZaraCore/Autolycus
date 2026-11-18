"""Read backend channel/group buckets; never infer retry relationships."""
from datetime import datetime
import os

import httpx

from .collector import CollectionError
from .retry import retry
from .schedule import BEIJING
from .markdown import escape, table


def count(value):
    if type(value) is not int or value < 0:
        raise ValueError("次数必须为非负整数")
    return value


def parse(payload, dimension):
    try:
        if payload.get("success") is not True:
            raise ValueError("业务失败")
        data = payload["data"]
        if data["dimension"] != dimension:
            raise ValueError("维度不一致")
        start, end = count(data["start_ts"]), count(data["end_ts"])
        if end <= start:
            raise ValueError("时间区间无效")
        rows, seen = [], set()
        for raw in data["rows"]:
            key = str(raw["key"])
            if key in seen:
                raise ValueError("重复汇总行")
            seen.add(key)
            success = failure = 0
            buckets = set()
            for bucket in raw["buckets"]:
                stamp = count(bucket["bucket_start"])
                if stamp in buckets:
                    raise ValueError("重复时间桶")
                buckets.add(stamp)
                success += count(bucket["consume"])
                failure += count(bucket["error"])
            errors = {}
            for entry in raw.get("error_distribution", []):
                code = str(entry["status_code"])
                errors[code] = errors.get(code, 0) + count(entry["count"])
            rows.append(dict(key=key, name=str(raw["name"]), success=success, failure=failure,
                             total=success + failure, errors=sorted(errors.items(), key=lambda item: (-item[1], item[0]))[:3]))
        return dict(start=start, end=end, dimension=dimension,
                    rows=sorted(rows, key=lambda row: (-row["total"], row["key"])))
    except (KeyError, TypeError, ValueError, AttributeError, OverflowError):
        raise CollectionError(f"渠道监控 {dimension} 响应结构或次数无效") from None


def collect_monitor(config, dimension, duration, client=None):
    options = config["channel_monitor"]
    token = os.environ.get("AUTOLYCUS_ACCESS_TOKEN", "").strip()
    if not token:
        raise CollectionError("缺少后台访问令牌")
    headers = {"Authorization": f"Bearer {token}"}
    if user := os.environ.get("AUTOLYCUS_USER_ID"):
        headers["New-Api-User"] = user
    body = {"dimension": dimension, "range_sec": duration, "window_sec": 300}
    if dimension == "channel":
        body.update(channel_ids=[], include_error_distribution=True)
    else:
        body.update(groups=[], aggregate_retries=True)
    def request(active):
        try:
            response = active.post(config["site"]["base_url"].rstrip("/") + options["path"],
                                   params={"Action": "Query"}, json=body, headers=headers,
                                   timeout=config["site"].get("timeout_seconds", 20))
            response.raise_for_status()
            payload = response.json()
        except httpx.HTTPStatusError as exc:
            code = exc.response.status_code
            raise CollectionError(f"渠道监控 HTTP {code}", retryable=code in (408, 429) or code >= 500) from None
        except httpx.RequestError:
            raise CollectionError("渠道监控网络请求失败", retryable=True) from None
        except ValueError:
            raise CollectionError("渠道监控响应不是 JSON") from None
        return parse(payload, dimension)
    if client is not None:
        return request(client)
    with httpx.Client(follow_redirects=False) as active:
        return request(active)


def clean(value):
    return " ".join(value.split())[:100]


def render_monitor(data, start, end):
    dimension = data["dimension"]
    actual_start = datetime.fromtimestamp(data["start"], BEIJING)
    actual_end = datetime.fromtimestamp(data["end"], BEIJING)
    title = "渠道成功率｜按调用量前20" if dimension == "channel" else "分组成功率｜后台重试聚合"
    lines = ["## " + title, "", f"实际区间：{actual_start:%m-%d %H:%M:%S}—{actual_end:%m-%d %H:%M:%S}（北京时间）", ""]
    rows = data["rows"][:20] if dimension == "channel" else data["rows"]
    if not data["rows"]:
        lines.append("后台未返回记录，不能据此判断全部正常。")
    if dimension == "group":
        rows = [row for row in rows if row["total"] > 0 and row["success"] * 100 < row["total"] * 95]
        if data["rows"] and not rows:
            lines.append("无成功率低于95%的分组（仅检查有调用记录的分组）。")
    entries = []
    for row in rows:
        rate = f"{row['success'] / row['total']:.2%}" if row["total"] else "无调用"
        name = f"(#{clean(row['key'])}) {clean(row['name'])}" if dimension == "channel" else clean(row["name"])
        entry = [escape(name), rate, f"{row['success']}/{row['total']}"]
        if dimension == "channel":
            errors = "、".join(f"{code}({number})" for code, number in row["errors"])
            entry.append(escape(errors or ("无失败" if not row["failure"] else "后台未提供错误码分布")))
        entries.append(entry)
    if entries:
        headers = ["渠道" if dimension == "channel" else "分组", "成功率", "成功/总量"]
        if dimension == "channel":
            headers.append("主要错误（次数）")
        lines.append(table(headers, entries))
    return "\n".join(lines)


def supplement(config, start, end):
    if not config.get("channel_monitor", {}).get("enabled", False):
        return ""
    sections = []
    for dimension in ("channel", "group"):
        try:
            data = retry(lambda: collect_monitor(config, dimension, int((end-start).total_seconds())))
            sections.append(render_monitor(data, start, end))
        except (CollectionError, ValueError, OverflowError, OSError) as exc:
            label = "分渠道" if dimension == "channel" else "分组聚合"
            sections.append(f"## {label}\n\n> {label}：数据不可用（{type(exc).__name__}），此项未完成巡检。")
    return "\n\n" + "\n\n".join(sections)
