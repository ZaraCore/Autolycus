"""Bounded single-slot worker invoked by cron (Windows uses its own entry)."""
from datetime import datetime
import logging
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time

from .config import load_config
from .schedule import BEIJING, due_slot, settings, slot_key
from .scheduled import begin_tracking
from .storage import Store


class StopEvent(threading.Event):
    """Container shutdown flag reaches cron jobs in separate process groups."""
    def __init__(self, path):
        super().__init__()
        self.path = Path(path)

    def is_set(self):
        return super().is_set() or self.path.exists()

    def wait(self, timeout=None):
        deadline = None if timeout is None else time.monotonic() + timeout
        while not self.is_set():
            remaining = 1 if deadline is None else deadline - time.monotonic()
            if remaining <= 0:
                return False
            super().wait(min(1, remaining))
        return True


def preflight(config):
    settings(config)
    if not config["notification"]["enabled"]:
        raise ValueError("容器自动汇报要求 notification.enabled=true")
    if config["query"].get("mode") != "absolute":
        raise ValueError("容器部署要求固定区间查询")
    if ".example" in config["site"]["base_url"]:
        raise ValueError("请配置真实后台地址")
    for name in ("AUTOLYCUS_ACCESS_TOKEN", "AUTOLYCUS_FEISHU_WEBHOOK"):
        if not os.getenv(name, "").strip():
            raise ValueError(f"缺少环境变量 {name}")


def eligible(config, now, attempted):
    slot = due_slot(config, now)
    if slot is None:
        return None
    key = slot_key(config, slot)
    if attempted.get(key, 0) >= 3:
        return None
    store = Store(config["storage"]["path"])
    try:
        row = store.db.execute("SELECT status,attempts,started FROM scheduled_runs WHERE key=?", (key,)).fetchone()
        if row and (row[0] == "sent" or row[1] >= 3):
            return None
        if row and row[0] == "running" and (now - datetime.fromisoformat(row[2])).total_seconds() < 300:
            return None
    finally:
        store.close()
    return key


def supervise(config_path, stop=None):
    """One cron invocation; retries belong to this slot, never an idle loop."""
    config_path = str(Path(config_path).resolve())
    config = load_config(config_path)
    preflight(config)
    stop = stop or threading.Event()
    data = Path(config["storage"]["path"]).parent
    data.mkdir(parents=True, exist_ok=True)
    import fcntl
    with (data / "cron-job.lock").open("a") as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            logging.info("前一次巡检尚未结束，跳过重叠任务")
            return
        begin_tracking(config)
        slot = due_slot(config, datetime.now(BEIJING))
        if slot is None:
            return
        key = slot_key(config, slot)
        result = 0
        for attempt in range(3):
            if stop.is_set() or eligible(config, datetime.now(BEIJING), {}) != key:
                break
            result = 1
            logging.info("启动计划巡检 attempt=%s", attempt + 1)
            process = subprocess.Popen([sys.executable, "-u", "-m", "autolycus", "--config", config_path, "--scheduled"])
            deadline = time.monotonic() + 240
            interrupted = False
            while process.poll() is None:
                if stop.is_set() or time.monotonic() >= deadline:
                    interrupted = True
                    process.terminate()
                    try:
                        process.wait(timeout=15)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
                    break
                stop.wait(1)
            logging.info("巡检结束 exit=%s interrupted=%s", process.returncode, interrupted)
            if interrupted:
                store = Store(config["storage"]["path"])
                try:
                    with store.db:
                        store.db.execute("UPDATE scheduled_runs SET status='failed', detail='cron runner terminated child' WHERE key=? AND status='running'", (key,))
                finally:
                    store.close()
            if process.returncode == 0:
                result = 0
                break
            if stop.is_set():
                break
            if attempt < 2:
                stop.wait(60)
        return result


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="/etc/autolycus/config.toml")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        data = Path(load_config(args.config)["storage"]["path"]).parent
        stop = StopEvent(data / "cron.stop")
        for name in (signal.SIGINT, signal.SIGTERM):
            signal.signal(name, lambda signum, frame: stop.set())
        return supervise(args.config, stop) or 0
    except (OSError, ValueError) as exc:
        logging.error("调度启动失败 category=%s", type(exc).__name__)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
