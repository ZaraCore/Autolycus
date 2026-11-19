from pathlib import Path
import math
import tomllib
import os
from .highlight import settings as highlight_settings
from urllib.parse import urlsplit


def load_config(path):
    path = Path(path).resolve()
    with path.open("rb") as stream:
        config = tomllib.load(stream)
    overrides = {"AUTOLYCUS_BASE_URL": ("site", "base_url"), "AUTOLYCUS_SITE_ID": ("site", "id"), "AUTOLYCUS_SITE_NAME": ("site", "name"), "AUTOLYCUS_DATABASE": ("storage", "path")}
    for variable, (section, key) in overrides.items():
        if variable in os.environ:
            config.setdefault(section, {})[key] = os.environ[variable]
    for section in ("site", "query", "fields", "rules", "storage", "notification"):
        if section not in config:
            raise ValueError(f"缺少配置段：{section}")
    for field in ("id", "name", "source", "scope", "base_url", "metrics_path"):
        if not isinstance(config["site"].get(field), str) or not config["site"][field].strip():
            raise ValueError(f"缺少站点配置：{field}")
    site = config["site"]
    url = urlsplit(site["base_url"])
    if url.scheme != "https" or not url.hostname or url.username or url.password or url.query or url.fragment:
        raise ValueError("后台地址必须使用 HTTPS，且不能包含账号、查询参数或片段")
    endpoint = urlsplit(site["metrics_path"])
    if not site["metrics_path"].startswith("/") or endpoint.scheme or endpoint.netloc or endpoint.query or endpoint.fragment:
        raise ValueError("metrics_path 必须是站内绝对路径，查询条件放在 query.filters")
    for name in ("total", "success", "failure"):
        if not isinstance(config["fields"].get(name), str) or not config["fields"][name]:
            raise ValueError(f"缺少字段映射：{name}")
    rules = config["rules"]
    for name in ("min_requests", "history_days"):
        if type(rules.get(name)) is not int or rules[name] < 1:
            raise ValueError(f"{name} 必须是正整数")
    for name, upper in (("success_rate_min", 1), ("max_drop_points", 100)):
        value = rules.get(name)
        if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= upper:
            raise ValueError(f"{name} 超出有效范围")
    timeout = site.get("timeout_seconds", 20)
    if type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("timeout_seconds 必须为正数")
    query = config["query"]
    mode = query.get("mode", "absolute")
    if mode not in ("absolute", "relative"):
        raise ValueError("query.mode 必须是 absolute 或 relative")
    if mode == "relative":
        if query.get("range", "1h") != "1h":
            raise ValueError("滚动查询目前仅支持 range=1h")
        if "range" in query.get("filters", {}):
            raise ValueError("filters 不能覆盖 range")
    else:
        for name in ("start_parameter", "end_parameter"):
            if not isinstance(query.get(name), str) or not query[name]:
                raise ValueError(f"缺少查询配置：{name}")
        if query["start_parameter"] == query["end_parameter"]:
            raise ValueError("起止时间参数不能相同")
        if set(query.get("filters", {})) & {query["start_parameter"], query["end_parameter"]}:
            raise ValueError("filters 不能覆盖时间参数")
    if type(config["notification"].get("enabled")) is not bool:
        raise ValueError("notification.enabled 必须是布尔值")
    database = Path(config["storage"]["path"])
    if monitor := config.get("channel_monitor"):
        if type(monitor.get("enabled")) is not bool:
            raise ValueError("channel_monitor.enabled 必须是布尔值")
        monitor_path = monitor.get("path", "")
        parsed = urlsplit(monitor_path)
        if not monitor_path.startswith("/") or parsed.netloc or parsed.scheme or parsed.query or parsed.fragment:
            raise ValueError("channel_monitor.path 必须是站内路径")
    if performance := config.get("model_performance"):
        if type(performance.get("enabled")) is not bool:
            raise ValueError("model_performance.enabled 必须是布尔值")
        targets = performance.get("targets", [])
        if not isinstance(targets, list) or (performance["enabled"] and not targets):
            raise ValueError("模型延迟需配置非空 targets 列表")
        seen = set()
        for target in targets:
            if not isinstance(target, dict) or any(not isinstance(target.get(key), str) or not target[key].strip() or any(char in target[key] for char in '\r\n') for key in ("group", "model")):
                raise ValueError("每个模型延迟目标需填写有效 group 和 model")
            pair = (target["group"], target["model"])
            if pair in seen:
                raise ValueError("模型延迟目标不能重复")
            seen.add(pair)
    highlight_settings(config)
    config["storage"]["path"] = str(database if database.is_absolute() else path.parent / database)
    return config
