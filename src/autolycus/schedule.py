"""Pure Beijing-time scheduling; no OS or network effects."""
from datetime import datetime, timedelta, timezone

BEIJING = timezone(timedelta(hours=8))
WEEKDAY = ["02:30", "05:30", "08:30", *[f"{h:02}:30" for h in range(9, 18)], "20:30", "23:30"]
WEEKEND = ["05:30", "11:30", "17:30", "23:30"]


def settings(config):
    result = {"weekday_times": WEEKDAY, "weekend_times": WEEKEND, "grace_minutes": 10,
              **config.get("schedule", {})}
    for name in ("weekday_times", "weekend_times"):
        values = result[name]
        if not isinstance(values, list) or not values or len(set(values)) != len(values):
            raise ValueError(f"schedule.{name} 必须是非空且无重复的时间列表")
        for value in values:
            if not isinstance(value, str) or len(value) != 5:
                raise ValueError("计划时间格式必须为 HH:MM")
            try:
                parsed = datetime.strptime(value, "%H:%M")
            except ValueError:
                raise ValueError("计划时间格式必须为 HH:MM") from None
            if value != parsed.strftime("%H:%M"):
                raise ValueError("计划时间格式必须为 HH:MM")
    if type(result["grace_minutes"]) is not int or not 0 <= result["grace_minutes"] <= 15:
        raise ValueError("grace_minutes 必须为 0 到 15 的整数")
    if result.get("interval_mode", "fixed_1h") not in ("fixed_1h", "planned_chain"):
        raise ValueError("interval_mode 必须为 fixed_1h 或 planned_chain")
    return result


def slots_between(config, start, end):
    if start.tzinfo is None or end.tzinfo is None:
        raise ValueError("调度时间必须有时区")
    start, end = start.astimezone(BEIJING), end.astimezone(BEIJING)
    options = settings(config)
    day = start.replace(hour=0, minute=0, second=0, microsecond=0)
    result = []
    while day <= end:
        name = "weekday_times" if day.weekday() < 5 else "weekend_times"
        for value in sorted(options[name]):
            hour, minute = map(int, value.split(":"))
            slot = day.replace(hour=hour, minute=minute)
            if start <= slot <= end:
                result.append(slot)
        day += timedelta(days=1)
    return result


def due_slot(config, now):
    grace = settings(config)["grace_minutes"]
    candidates = slots_between(config, now - timedelta(minutes=grace), now)
    return candidates[-1] if candidates else None


def inspection_window(config, slot):
    """Previous planned occurrence to this occurrence, independent of delays.

    Enumerate eight days so weekday/weekend transitions are included. This
    computes a planned window; it does not imply that a backend supports it.
    """
    if slot.tzinfo is None:
        raise ValueError("巡检计划时间必须有时区")
    slot = slot.astimezone(BEIJING)
    occurrences = slots_between(config, slot - timedelta(days=8), slot)
    if not occurrences or occurrences[-1] != slot or len(occurrences) < 2:
        raise ValueError("给定时间不是有效巡检计划，或没有前一计划时间")
    return occurrences[-2], slot


def slot_key(config, slot):
    from .collector import scope_key
    return f"scheduled:{config['site']['id']}:{config['site']['source']}:{scope_key(config)}:{slot.isoformat()}"
