def render(metrics, assessment, demo=False):
    if not demo:
        lines = ["Autolycus 巡检",
                 f"站点：{metrics.site_name}",
                 f"时段：{metrics.start:%Y-%m-%d %H:%M} 至 {metrics.end:%Y-%m-%d %H:%M}（北京时间）"]
        if metrics.window_kind == "relative":
            lines.append("统计方式：后台最近一小时滚动统计；时段按本地请求时间估算")
        return "\n".join(lines)
    rate = f"{metrics.success_rate:.2%}" if metrics.success_rate is not None else "不适用"
    status = "成功率触发阈值" if assessment.status == "异常" else assessment.status
    lines = [f"{'【演示数据】' if demo else ''}Autolycus 巡检 · {status}",
             f"站点：{metrics.site_name}",
             f"时段：{metrics.start:%Y-%m-%d %H:%M} 至 {metrics.end:%Y-%m-%d %H:%M}（北京时间）",
             f"调用量：{metrics.total:,}；成功：{metrics.success:,}；失败：{metrics.failure:,}",
             f"成功率：{rate}"]
    if assessment.baseline is not None:
        lines.append(f"历史基准：{assessment.baseline:.2%}（此前工作日同时段，按调用量加权）")
    if metrics.window_kind == "relative":
        lines.insert(2, "统计方式：后台最近一小时滚动统计；下列时段按本地请求时间估算")
        lines.append("历史比较：暂未启用滚动快照比较，本次仅检查固定阈值")
    for label, value in (("P50", metrics.p50_seconds), ("P95", metrics.p95_seconds)):
        lines.append(f"总耗时 {label}：{value:.1f} 秒" if value is not None else f"总耗时 {label}：无数据")
    if metrics.latency_samples is not None:
        lines.append(f"耗时样本数：{metrics.latency_samples:,}")
    lines.extend(f"说明：{reason}" for reason in assessment.reasons)
    return "\n".join(lines)
