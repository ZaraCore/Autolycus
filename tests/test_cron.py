from datetime import datetime, timedelta
from pathlib import Path
import sys
import types

import pytest

from autolycus import daemon, maintenance
from autolycus.config import load_config
from autolycus.cron import crontab
from autolycus.schedule import BEIJING, slots_between


def test_cron_matches_entire_week_and_non_hourly_configuration():
    config = load_config("config/deployment.example.toml")
    for times in (None, ["09:15", "10:30", "17:15"]):
        if times:
            config["schedule"]["weekday_times"] = times
        lines = [line.split()[:5] for line in crontab(config, "config.toml").splitlines() if not line.startswith("#")]
        monday = datetime(2026, 11, 16, tzinfo=BEIJING)
        expected = set(slots_between(config, monday, monday + timedelta(days=7, minutes=-1)))
        actual = set()
        for offset in range(7 * 1440):
            now = monday + timedelta(minutes=offset)
            for minute, hours, day, month, weekdays in lines:
                if now.minute == int(minute) and now.hour in map(int, hours.split(",")) and ((now.weekday() < 5) if weekdays == "1-5" else (now.weekday() >= 5)):
                    actual.add(now)
        assert actual == expected
        assert len(actual) == (21 if times else 56)
    assert "autolycus.daemon" in crontab(config, "config.toml")


def test_cron_rejects_percent_path_and_never_contains_credentials(monkeypatch):
    config = load_config("config/deployment.example.toml")
    monkeypatch.setenv("AUTOLYCUS_ACCESS_TOKEN", "do-not-write-token")
    assert "do-not-write-token" not in crontab(config, "config.toml")
    with pytest.raises(ValueError):
        crontab(config, "config%bad.toml")


def test_cron_health_does_not_expire_while_idle_and_detects_reused_pid(tmp_path, monkeypatch):
    path = tmp_path / "heartbeat.json"
    maintenance.heartbeat(path, state="cron", pid=123, identity="boot:100")
    monkeypatch.setattr(maintenance, "process_identity", lambda pid: "boot:100")
    monkeypatch.setattr(maintenance.time, "time", lambda: 99999999999)
    assert maintenance.healthy(path)
    monkeypatch.setattr(maintenance, "process_identity", lambda pid: "boot:101")
    assert not maintenance.healthy(path)
    monkeypatch.setattr(maintenance, "process_identity", lambda pid: (_ for _ in ()).throw(FileNotFoundError()))
    assert not maintenance.healthy(path)


def test_shutdown_flag_interrupts_retry_wait(tmp_path):
    flag = tmp_path / "cron.stop"
    event = daemon.StopEvent(flag)
    assert not event.is_set()
    flag.touch()
    assert event.wait(60)
    assert event.is_set()


def test_worker_retries_only_same_slot_and_no_retry_after_success(tmp_path, monkeypatch):
    config = load_config("config/deployment.example.toml")
    config["storage"]["path"] = str(tmp_path / "db.sqlite")
    config["site"]["base_url"] = "https://backend.test"
    monkeypatch.setenv("AUTOLYCUS_ACCESS_TOKEN", "test")
    monkeypatch.setenv("AUTOLYCUS_FEISHU_WEBHOOK", "test")
    monkeypatch.setattr(daemon, "load_config", lambda path: config)
    slot = datetime(2026, 11, 19, 10, tzinfo=BEIJING)
    monkeypatch.setattr(daemon, "datetime", types.SimpleNamespace(now=lambda tz: slot))
    if sys.platform == "win32":
        monkeypatch.setitem(sys.modules, "fcntl", types.SimpleNamespace(LOCK_EX=1, LOCK_NB=2, flock=lambda *args: None))
    calls = []
    class Child:
        def __init__(self, command):
            calls.append(command)
            self.returncode = 1 if len(calls) == 1 else 0
        def poll(self):
            return self.returncode
    class Stop:
        waits = []
        def is_set(self): return False
        def wait(self, seconds): self.waits.append(seconds)
    stop = Stop()
    monkeypatch.setattr(daemon.subprocess, "Popen", Child)
    daemon.supervise("config.toml", stop)
    assert len(calls) == 2
    assert stop.waits == [60]
    calls.clear()
    # No new slot may be picked up inside a retry of the original task.
    keys = iter([daemon.slot_key(config, slot), "different-slot"])
    monkeypatch.setattr(daemon, "eligible", lambda *args: next(keys))
    daemon.supervise("config.toml", stop)
    assert len(calls) == 1
