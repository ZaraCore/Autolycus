"""Per-group model latency from backend consumption-log statistics."""
from copy import deepcopy
import logging

import httpx

from .collector import CollectionError, collect
from .retry import retry


def target_config(config, target):
    result = deepcopy(config)
    if result["query"].get("mode", "absolute") != "absolute":
        raise CollectionError("模型延迟需要固定时间区间查询")
    result["query"].setdefault("filters", {}).update(
        group=target["group"], model_name=target["model"], log_type=2)
    return result


def latency_line(metrics, model):
    if metrics.failure != 0 or metrics.total != metrics.success:
        raise CollectionError("消费日志筛选未生效：响应仍包含失败请求")
    if not metrics.success:
        return None
    if metrics.latency_samples == 0:
        latency = "无有效耗时样本"
    else:
        def display(value):
            return f"{value:.1f}秒" if value is not None else "无数据"
        latency = f"P50 {display(metrics.p50_seconds)}｜P95 {display(metrics.p95_seconds)}"
    return f"{model}：成功{metrics.success:,}次｜{latency}"


def supplement_models(config, start, end, client=None):
    options = config.get("model_performance", {})
    if not options.get("enabled", False):
        return ""
    def run(active):
        groups = {}
        for target in options["targets"]:
            group, model = target["group"], target["model"]
            logging.getLogger("autolycus").info("阶段：查询重点模型成功日志延迟")
            try:
                metrics = retry(lambda: collect(target_config(config, target), start, end, active))
                line = latency_line(metrics, model)
                if line:
                    groups.setdefault(group, []).append(line)
            except CollectionError as exc:
                groups.setdefault(group, []).append(f"{model}：数据不可用（{type(exc).__name__}），未完成此项检查")
        lines = ["重点模型延迟｜消费日志（log_type=2）"]
        for group, entries in groups.items():
            lines.append(f"{group}分组：")
            lines.extend(entries)
        if not groups:
            lines.append("已配置模型本时段均无成功消费记录，不展示延迟。")
        return "\n\n" + "\n".join(lines)
    if client is not None:
        return run(client)
    with httpx.Client(follow_redirects=False) as active:
        return run(active)
