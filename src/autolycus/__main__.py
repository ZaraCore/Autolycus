import argparse
from datetime import datetime, timedelta, timezone
import logging
import sqlite3
from logging.handlers import RotatingFileHandler
from pathlib import Path

from .collector import CollectionError
from .config import load_config
from .feishu import NotificationError
from .job import execute
from .credentials import initialize, load_credentials, read_credentials
from .schedule import settings, slots_between, inspection_window
from .scheduled import begin_tracking, run_scheduled, status_report

BEIJING = timezone(timedelta(hours=8))


def parse_time(value):
    result = datetime.fromisoformat(value)
    if result.tzinfo is None:
        raise ValueError("时间必须携带时区，例如 2026-11-13T09:00:00+08:00")
    return result.astimezone(BEIJING)


def main():
    parser = argparse.ArgumentParser(description="Autolycus：执行一次后台巡检，默认仅预览")
    parser.add_argument("--config", default="config.example.toml")
    parser.add_argument("--demo", choices=["normal", "abnormal", "empty"])
    parser.add_argument("--start", help="带时区的起始时间")
    parser.add_argument("--end", help="带时区的结束时间")
    parser.add_argument("--notify", action="store_true", help="明确启用本次飞书发送")
    parser.add_argument("--force", action="store_true", help="允许重发已发送时段")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--init-credentials", action="store_true", help="隐藏输入并加密保存凭据")
    modes.add_argument("--save-env-credentials", action="store_true", help="加密保存当前环境变量中的凭据")
    modes.add_argument("--check-credentials", action="store_true", help="仅验证持久凭据可解密，不显示值")
    modes.add_argument("--scheduled", action="store_true", help="按北京时间计划判断是否执行并推送")
    modes.add_argument("--schedule-preview", action="store_true", help="预览未来七天计划，不查询后台")
    modes.add_argument("--status", action="store_true", help="核对近七天计划执行结果")
    modes.add_argument("--begin-tracking", action="store_true", help="开始持续运行追踪，不发送")
    args = parser.parse_args()
    logger = logging.getLogger("autolycus")
    try:
        if bool(args.start) != bool(args.end):
            raise ValueError("--start 和 --end 必须一起提供")
        config = load_config(args.config)
        settings(config)
        credentials_path = Path(config["storage"]["path"]).parent / "credentials.dpapi"
        if args.init_credentials or args.save_env_credentials:
            initialize(credentials_path, from_environment=args.save_env_credentials)
            return 0
        if args.check_credentials:
            read_credentials(credentials_path)
            print("当前 Windows 用户可以解密持久凭据；未访问网络、未显示密钥。")
            return 0
        if args.scheduled and (args.demo or args.start or args.end or args.force):
            raise ValueError("--scheduled 不能与演示、指定时段或强制重发一起使用")
        if args.schedule_preview:
            now = datetime.now(BEIJING)
            print("未来七天计划（北京时间，周一至周五为工作日）：")
            for slot in slots_between(config, now, now + timedelta(days=7)):
                if settings(config).get("interval_mode") == "planned_chain":
                    left, right = inspection_window(config, slot)
                    print(f"汇报 {slot:%Y-%m-%d %H:%M}；统计 {left:%Y-%m-%d %H:%M} 至 {right:%Y-%m-%d %H:%M}")
                else:
                    print(slot.isoformat())
            return 0
        if args.status:
            print(status_report(config))
            return 0
        if args.begin_tracking:
            begin_tracking(config)
            print("持续运行追踪已启用。")
            return 0
        # Preview/status never require secrets. Noninteractive execution loads
        # encrypted credentials without getpass prompts.
        relative = config["query"].get("mode", "absolute") == "relative" and not args.demo
        if relative and args.start:
            raise ValueError("当前接口只确认支持 range=1h，不能指定历史起止时间；请去掉 --start 和 --end")
        if args.demo:
            db = Path(config["storage"]["path"])
            config["storage"]["path"] = str(db.with_name(db.stem + ".demo" + db.suffix))
        log_path = Path(config["storage"]["path"]).parent / "logs" / "autolycus.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(log_path, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        if not args.demo or args.notify:
            load_credentials(credentials_path)
        if args.scheduled:
            print(run_scheduled(config))
            logger.info("本次定时检查完成")
            return 0
        if args.start:
            start, end = parse_time(args.start), parse_time(args.end)
        else:
            now = datetime.now(BEIJING)
            end = now.replace(microsecond=0) if relative else now.replace(minute=0, second=0, microsecond=0)
            start = end - timedelta(hours=1)
            if not args.demo and not relative and settings(config).get("interval_mode") == "planned_chain":
                latest = slots_between(config, now - timedelta(days=8), now)[-1]
                start, end = inspection_window(config, latest)
        if not relative and (start >= end or end - start > timedelta(days=7)):
            raise ValueError("固定查询区间必须为正且不超过七天")
        if not relative and not args.demo and start < datetime.now(BEIJING) - timedelta(days=7):
            raise ValueError("后台页面提示仅支持最近七天，请选择更近的起始时间")
        if end > datetime.now(BEIJING):
            raise ValueError("不能查询尚未结束的时段")
        logger.info("开始巡检 mode=%s start=%s", args.demo or "live", start.isoformat())
        print(execute(config, start, end, args.demo, args.notify, args.force))
        logger.info("巡检完成")
        return 0
    except (OSError, ValueError, CollectionError, NotificationError) as exc:
        print(f"执行失败：{exc}")
        logger.error("执行失败 category=%s", type(exc).__name__)
        return 1
    except sqlite3.Error:
        print("执行失败：数据库不可访问或结构异常，请检查数据库路径、磁盘及文件权限")
        logger.error("执行失败 category=DatabaseError")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
