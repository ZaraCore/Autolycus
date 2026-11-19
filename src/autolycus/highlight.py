"""Feishu display thresholds, independent of collection and assessment rules."""
import math


DEFAULTS = {"enabled": True, "success_red_below": 70, "success_orange_below": 95,
            "p50_orange_above_seconds": 60, "p95_orange_above_seconds": 120,
            "latency_red_multiplier": 2}


def settings(config=None):
    values = {**DEFAULTS, **(config or {}).get("highlight", {})}
    if type(values["enabled"]) is not bool:
        raise ValueError("highlight.enabled 必须是布尔值")
    for key in DEFAULTS.keys() - {"enabled"}:
        value = values[key]
        if type(value) not in (int, float) or not math.isfinite(value):
            raise ValueError(f"highlight.{key} 必须是有限数值")
    if not 0 <= values["success_red_below"] <= values["success_orange_below"] <= 100:
        raise ValueError("成功率颜色阈值必须满足 0 <= 红色 <= 橙色 <= 100")
    if (values["p50_orange_above_seconds"] <= 0 or values["p95_orange_above_seconds"] <= 0
            or values["latency_red_multiplier"] <= 1):
        raise ValueError("延迟阈值必须为正数，红色倍数必须大于 1")
    return values


def color(text, name, config=None):
    return f"<font color='{name}'>{text}</font>" if settings(config)["enabled"] else text


def success(text, count, total, config=None):
    options = settings(config)
    if total:
        for name in ("red", "orange"):
            if count * 100 < total * options[f"success_{name}_below"]:
                return color(text, name, config)
        if count * 100 > total * 95:
            return color(text, "green", config)
    return text


def latency(text, value, percentile, config=None):
    if value is None:
        return color(text, "red", config)
    options = settings(config)
    limit = options[f"{percentile}_orange_above_seconds"]
    if value > limit * options["latency_red_multiplier"]:
        return color(text, "red", config)
    if value > limit:
        return color(text, "orange", config)
    return text
