"""Generate Beijing-time cron jobs and supervise container-friendly Supercronic."""
import argparse
import logging
import os
from pathlib import Path
import shlex
import signal
import subprocess
import sys

from .config import load_config
from .daemon import preflight
from .maintenance import heartbeat, process_identity
from .schedule import settings
from .scheduled import begin_tracking


def crontab(config, config_path):
    # shlex protects the command; cron treats '%' specially even inside quotes.
    values = (sys.executable, str(Path(config_path).resolve()))
    if any(any(c in v for c in "\r\n%") for v in values):
        raise ValueError("cron command paths cannot contain newline or %")
    command = f"{shlex.quote(values[0])} -u -m autolycus.daemon --config {shlex.quote(values[1])}"
    lines = ["# Generated from config.toml; timezone: Asia/Shanghai"]
    options = settings(config)
    for name, days in (("weekday_times", "1-5"), ("weekend_times", "0,6")):
        by_minute = {}
        for value in sorted(options[name]):
            hour, minute = map(int, value.split(":"))
            by_minute.setdefault(minute, []).append(hour)
        for minute, hours in sorted(by_minute.items()):
            lines.append(f"{minute} {','.join(map(str, hours))} * * {days} {command}")
    return "\n".join(lines) + "\n"


def serve(config_path):
    import fcntl
    config_path = str(Path(config_path).resolve())
    config = load_config(config_path)
    preflight(config)
    data = Path(config["storage"]["path"]).parent
    data.mkdir(parents=True, exist_ok=True)
    with (data / "daemon.lock").open("a") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        path = data / "crontab"
        path.write_text(crontab(config, config_path), encoding="utf-8")
        stopped = data / "cron.stop"
        stopped.unlink(missing_ok=True)
        # Credentials are inherited, never written to the cron file.
        env = dict(os.environ, TZ="Asia/Shanghai")
        subprocess.run(["/usr/local/bin/supercronic", "-test", str(path)], env=env, check=True)
        begin_tracking(config)
        process = subprocess.Popen(["/usr/local/bin/supercronic", str(path)], env=env,
                                   start_new_session=True)
        def stop(signum, frame):
            # Supercronic creates separate job process groups. The flag also
            # wakes their StopEvent during collection and retry waits.
            stopped.touch()
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        previous = {sig: signal.signal(sig, stop) for sig in (signal.SIGTERM, signal.SIGINT)}
        try:
            heartbeat(data / "heartbeat.json", state="cron", pid=process.pid,
                      identity=process_identity(process.pid))
            logging.info("cron 已启动，按北京时间计划触发；启动时不补执行历史任务")
            # No periodic scheduling/heartbeat loop; cron owns all time triggers.
            return process.wait()
        finally:
            stop(None, None)
            try:
                process.wait(timeout=20)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
            heartbeat(data / "heartbeat.json", state="stopped")
            for sig, handler in previous.items():
                signal.signal(sig, handler)


def main():
    parser = argparse.ArgumentParser(description="Run configured cron jobs in Beijing time")
    parser.add_argument("--config", default="/etc/autolycus/config.toml")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        return serve(args.config)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        logging.error("cron 启动失败 category=%s", type(exc).__name__)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
