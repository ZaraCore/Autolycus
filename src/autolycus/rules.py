from .models import Assessment


def assess(metrics, rules, baseline=None):
    if metrics.total == 0:
        return Assessment("无调用", ["本时段没有调用，不计算成功率"], baseline)
    if metrics.total < rules["min_requests"]:
        return Assessment("待观察", [f"样本不足：{metrics.total} < {rules['min_requests']}"], baseline)
    rate = metrics.success_rate
    reasons = []
    if rate < rules["success_rate_min"]:
        reasons.append(f"成功率 {rate:.2%} 低于下限 {rules['success_rate_min']:.2%}")
    if baseline is not None:
        drop = (baseline - rate) * 100
        if drop > rules["max_drop_points"]:
            reasons.append(f"比历史基准下降 {drop:.2f} 个百分点，超过 {rules['max_drop_points']:g}")
    if reasons:
        return Assessment("异常", reasons, baseline)
    return Assessment("正常", ["已配置规则未发现异常" + ("；暂无历史基准，仅检查固定阈值" if baseline is None else "")], baseline)
