"""Local maintenance; never contacts backend or Feishu."""
import argparse
import json
import os
from pathlib import Path
import sqlite3
import time


def backup_database(source, destination):
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if source == destination or destination.exists():
        raise ValueError("备份目标必须为尚不存在的新文件")
    if not source.is_file():
        raise ValueError("数据库不存在，不能创建空备份")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(source.as_uri() + "?mode=ro", uri=True) as incoming:
        with sqlite3.connect(destination) as outgoing:
            incoming.backup(outgoing)
            if outgoing.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError("数据库备份完整性检查失败")
    return destination


def heartbeat(path, **fields):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps({"timestamp": time.time(), **fields}), encoding="utf-8")
    temporary.replace(path)


def process_identity(pid):
    """Linux boot + process start time; detects stale state/PID reuse."""
    if type(pid) is not int or pid <= 0:
        raise ValueError("invalid pid")
    fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
    if fields[0] == "Z":
        raise ValueError("process is a zombie")
    boot = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    return f"{boot}:{fields[19]}"


def healthy(path, max_age=300):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if data.get("state") == "cron":
            return process_identity(data["pid"]) == data["identity"]
        age = time.time() - data["timestamp"]
        return data.get("state") != "stopped" and 0 <= age < max_age
    except (OSError, ValueError, KeyError, TypeError):
        return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["backup", "health"])
    parser.add_argument("--database", default=os.getenv("AUTOLYCUS_DATABASE", "/var/lib/autolycus/autolycus.db"))
    parser.add_argument("--output")
    args = parser.parse_args()
    if args.action == "health":
        return 0 if healthy(Path(args.database).parent / "heartbeat.json") else 1
    if not args.output:
        parser.error("backup requires --output")
    print(backup_database(args.database, args.output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
