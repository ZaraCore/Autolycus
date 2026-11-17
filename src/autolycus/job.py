import hashlib
import logging

from .collector import CollectionError, collect
from .feishu import NotificationError, send
from .models import Metrics
from .report import render
from .rules import assess
from .storage import Store
from .retry import retry
from .channel_monitor import supplement
from .model_performance import supplement_models


def execute(config, start, end, demo=None, notify=False, force=False, notification_key=None):
    store = Store(config["storage"]["path"])
    try:
        if notification_key and (cached := store.pending_report(notification_key)):
            if not store.was_sent(notification_key):
                try:
                    retry(lambda: send(cached))
                except NotificationError:
                    store.notification(notification_key, "failed")
                    raise
                store.notification(notification_key, "sent")
            store.record_run("success", "定时报告已送达（复用已保存报告）")
            return cached + "\n通知：飞书发送成功（复用已保存报告）"
        if demo:
            success = {"normal": 920, "abnormal": 650, "empty": 0}[demo]
            total = 0 if demo == "empty" else 1000
            metrics = Metrics("demo", "演示站点（非真实数据）", "demo", "demo-v1", start, end,
                              total, success, total - success, 12.5 if total else None,
                              48.0 if total else None, total)
        else:
            try:
                logging.getLogger("autolycus").info("阶段：查询性能数据")
                metrics = retry(lambda: collect(config, start, end))
            except CollectionError as exc:
                alert_key = notification_key + ":collection-error" if notification_key else None
                if notify and config["notification"]["enabled"] and (not alert_key or not store.was_sent(alert_key)):
                    try:
                        # Do not include untrusted backend response or credentials.
                        retry(lambda: send(f"Autolycus 采集失败\n站点：{config['site']['name']}\n错误类别：{type(exc).__name__}\n未获得业务指标，不能判断平台正常；请检查本地执行记录。"))
                        if alert_key:
                            store.notification(alert_key, "sent")
                    except NotificationError:
                        store.record_run("alert_failed", "采集失败提醒也未送达，请检查网络或飞书配置")
                raise
        baseline = store.baseline(metrics, config["rules"])
        assessment = assess(metrics, config["rules"], baseline)
        store.save(metrics, assessment)
        report = render(metrics, assessment, demo=bool(demo))
        if not demo:
            logging.getLogger("autolycus").info("阶段：查询渠道和分组数据")
            report += supplement(config, start, end)
            report += supplement_models(config, start, end)
        if notification_key:
            report = f"计划时间：{end:%Y-%m-%d %H:%M}（北京时间）\n" + report
            store.save_report(notification_key, report)
        delivery = "未发送（预览模式）"
        if notify:
            if not config["notification"]["enabled"]:
                raise NotificationError("发送未启用：请将 notification.enabled 设为 true")
            identity = f"{metrics.site_id}|{metrics.source}|{metrics.scope}|{metrics.start.isoformat()}|{metrics.end.isoformat()}"
            key = notification_key or hashlib.sha256(identity.encode()).hexdigest()
            if store.was_sent(key) and not force:
                delivery = "本时段已发送，已跳过（需要重发时使用 --force）"
            else:
                try:
                    logging.getLogger("autolycus").info("阶段：发送飞书报告")
                    retry(lambda: send(report))
                except NotificationError:
                    store.notification(key, "failed")
                    raise
                store.notification(key, "sent")
                delivery = "飞书发送成功"
        store.record_run("success", f"{start.isoformat()} {assessment.status}; {delivery}")
        return report + "\n通知：" + delivery
    except Exception:
        # Avoid recording upstream bodies, URLs or credentials in error logs.
        store.record_run("failed", f"{start.isoformat()} 执行失败，请查看命令行错误类别")
        raise
    finally:
        store.close()
