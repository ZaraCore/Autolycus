from datetime import datetime, timedelta
import hashlib
import json

from .collector import scope_key
from .job import execute
from .schedule import BEIJING, due_slot, settings, slot_key, slots_between, inspection_window
from .storage import Store


def tracking_key(config):
    fingerprint = hashlib.sha256(json.dumps(settings(config), sort_keys=True).encode()).hexdigest()[:12]
    return f"{config['site']['id']}:{config['site']['source']}:{scope_key(config)}:{fingerprint}"


def begin_tracking(config, now=None):
    now = now or datetime.now(BEIJING)
    store = Store(config["storage"]["path"])
    try:
        with store.db:
            store.db.execute("INSERT OR IGNORE INTO tracking VALUES (?, ?)", (tracking_key(config), now.isoformat()))
    finally:
        store.close()


def run_scheduled(config, now=None):
    now = now or datetime.now(BEIJING)
    slot = due_slot(config, now)
    if slot is None:
        return "当前不在计划执行窗口，已跳过；不补发过期滚动数据。"
    if not config["notification"]["enabled"]:
        raise ValueError("定时投递需要 notification.enabled=true")
    if settings(config).get("interval_mode") == "planned_chain":
        if config["query"].get("mode", "absolute") != "absolute":
            raise ValueError("连续计划区间必须使用精确起止时间接口，不能使用滚动快照")
        start, end = inspection_window(config, slot)
    else:
        start, end = slot - timedelta(hours=1), slot
    begin_tracking(config, now)
    key = slot_key(config, slot)
    store = Store(config["storage"]["path"])
    try:
        if not store.claim_slot(key, slot, now):
            return "本计划已发送或正在执行，已跳过重复启动。"
        try:
            report = execute(config, start, end, notify=True, notification_key=key)
        except Exception as exc:
            store.finish_slot(key, "failed", datetime.now(BEIJING), type(exc).__name__)
            raise
        store.finish_slot(key, "sent", datetime.now(BEIJING), "飞书接口确认接收")
        return report
    finally:
        store.close()


def status_report(config, days=7, now=None):
    now = now or datetime.now(BEIJING)
    store = Store(config["storage"]["path"])
    try:
        tracking = store.db.execute("SELECT started FROM tracking WHERE id=?", (tracking_key(config),)).fetchone()
        if tracking is None:
            return "尚未开始本时间表的持续运行追踪；安装任务后将开始记录。"
        start = max(datetime.fromisoformat(tracking[0]), now - timedelta(days=days))
        slots = slots_between(config, start, now)
        totals = {"sent": 0, "failed": 0, "running": 0, "missing": 0, "waiting": 0}
        details = []
        for slot in slots:
            row = store.db.execute("SELECT status, detail FROM scheduled_runs WHERE key=?", (slot_key(config, slot),)).fetchone()
            state = row[0] if row else ("missing" if now - slot > timedelta(minutes=settings(config)["grace_minutes"]) else "waiting")
            totals[state] += 1
            if state != "sent":
                details.append(f"{slot:%m-%d %H:%M} {state}" + (f" ({row[1]})" if row and row[1] else ""))
        labels = {"sent": "飞书接口确认接收", "failed": "执行失败", "running": "执行中或中断待核查", "missing": "未执行/漏报", "waiting": "窗口内等待执行"}
        lines = [f"运行核对：{start:%Y-%m-%d %H:%M} 至 {now:%Y-%m-%d %H:%M}（北京时间）", f"计划次数：{len(slots)}"]
        lines.extend(f"{labels[key]}：{value}" for key, value in totals.items())
        lines.extend(details[-20:])
        lines.append("说明：sent 表示接口确认接收，仍需抽查群消息；missing 也可能由关机、休眠或未登录造成。")
        return "\n".join(lines)
    finally:
        store.close()
