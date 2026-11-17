from datetime import datetime, timedelta
import json
import os
from pathlib import Path
import sqlite3

import httpx
import pytest

from autolycus.collector import CollectionError, collect
from autolycus.config import load_config
from autolycus.credentials import NAMES, load_credentials, read_credentials, save_credentials
from autolycus.feishu import NotificationError
from autolycus.models import Metrics
from autolycus.retry import retry
from autolycus.schedule import BEIJING, due_slot, slots_between, slot_key
from autolycus.scheduled import begin_tracking, run_scheduled, status_report
from autolycus.storage import Store


def date(value):
    return datetime.fromisoformat(value).replace(tzinfo=BEIJING)


@pytest.fixture
def config(tmp_path):
    result = load_config("tests/fixtures/site_config.toml")
    # Legacy operating-policy tests remain pinned to their original contract.
    result["query"] = {"mode": "relative", "range": "1h", "filters": {}}
    result.pop("schedule", None)
    result["channel_monitor"]["enabled"] = False
    result["model_performance"]["enabled"] = False
    result["storage"]["path"] = str(tmp_path / "history.db")
    result["notification"]["enabled"] = True
    return result


def test_weekly_schedule_exactly_matches_agreement(config):
    week = slots_between(config, date("2026-11-09T00:00"), date("2026-11-15T23:59"))
    assert len(week) == 78
    monday = [slot.strftime("%H:%M") for slot in week if slot.weekday() == 0]
    assert monday == ["02:30", "05:30", "08:30", "09:30", "10:30", "11:30", "12:30", "13:30", "14:30", "15:30", "16:30", "17:30", "20:30", "23:30"]
    saturday = [slot.strftime("%H:%M") for slot in week if slot.weekday() == 5]
    assert saturday == ["05:30", "11:30", "17:30", "23:30"]
    friday_last = next(slot for slot in week if slot == date("2026-11-13T23:30"))
    assert week[week.index(friday_last) + 1] - friday_last == timedelta(hours=6)
    transition = slots_between(config, date("2026-11-15T23:30"), date("2026-11-16T03:00"))
    assert transition[1] - transition[0] == timedelta(hours=3)


def test_grace_and_beijing_timezone(config):
    assert due_slot(config, date("2026-11-13T09:29:59")) is None
    assert due_slot(config, date("2026-11-13T09:30")) == date("2026-11-13T09:30")
    assert due_slot(config, date("2026-11-13T09:40")) is not None
    assert due_slot(config, date("2026-11-13T09:40:01")) is None
    utc = datetime.fromisoformat("2026-11-13T01:30:00+00:00")
    assert due_slot(config, utc) == date("2026-11-13T09:30")


def test_retry_transient_only():
    attempts, waits = [], []
    def transient():
        attempts.append(1)
        if len(attempts) < 3:
            raise CollectionError("network", retryable=True)
        return "ok"
    assert retry(transient, sleep=waits.append) == "ok"
    assert waits == [2, 5]
    attempts.clear()
    def auth_error():
        attempts.append(1)
        raise CollectionError("401")
    with pytest.raises(CollectionError):
        retry(auth_error, sleep=waits.append)
    assert len(attempts) == 1


@pytest.mark.parametrize("code, expected", [(401, False), (403, False), (429, True), (503, True)])
def test_http_retry_classification(config, monkeypatch, code, expected):
    monkeypatch.setenv("AUTOLYCUS_ACCESS_TOKEN", "test")
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(code))) as client:
        with pytest.raises(CollectionError) as error:
            collect(config, date("2026-11-13T08:30"), date("2026-11-13T09:30"), client)
    assert error.value.retryable is expected


def test_cross_connection_claim_and_reclaim(config):
    a, b = Store(config["storage"]["path"]), Store(config["storage"]["path"])
    now = date("2026-11-13T09:30")
    try:
        assert a.claim_slot("key", now, now)
        assert not b.claim_slot("key", now, now)
        assert b.claim_slot("key", now, now + timedelta(minutes=5))
        b.finish_slot("key", "sent", now, "ok")
        assert not a.claim_slot("key", now, now + timedelta(minutes=6))
    finally:
        a.close()
        b.close()


def test_scheduled_failure_saved_report_retry_and_dedup(config, monkeypatch):
    reads, sends = [], []
    slot = date("2026-11-13T09:30")
    def collect_mock(*args):
        reads.append(1)
        return Metrics("synlink", "test", "platform", "scope", slot-timedelta(hours=1), slot,
                       1000, 900, 100, window_kind="relative")
    def fail_send(report):
        sends.append(report)
        raise NotificationError("temporary delivery failure")
    monkeypatch.setattr("autolycus.job.collect", collect_mock)
    monkeypatch.setattr("autolycus.job.send", fail_send)
    with pytest.raises(NotificationError):
        run_scheduled(config, slot)
    monkeypatch.setattr("autolycus.job.send", lambda report: sends.append(report))
    assert "复用" in run_scheduled(config, slot + timedelta(minutes=1))
    assert len(reads) == 1
    assert sends[0] == sends[1]
    assert "跳过" in run_scheduled(config, slot + timedelta(minutes=2))
    assert len(sends) == 2


def test_outside_schedule_does_not_collect(config, monkeypatch):
    def forbidden(*args):
        raise AssertionError("Must not access network outside schedule")
    monkeypatch.setattr("autolycus.job.collect", forbidden)
    assert "跳过" in run_scheduled(config, date("2026-11-14T09:30"))


def test_collection_failure_alert_and_next_slot_recovery(config, monkeypatch):
    messages = []
    def fail(*args):
        raise CollectionError("401")
    monkeypatch.setattr("autolycus.job.collect", fail)
    monkeypatch.setattr("autolycus.job.send", messages.append)
    now = date("2026-11-13T09:30")
    for offset in (0, 1):
        with pytest.raises(CollectionError):
            run_scheduled(config, now + timedelta(minutes=offset))
    assert len(messages) == 1
    assert "采集失败" in messages[0]
    def good(*args):
        end = now + timedelta(hours=1)
        return Metrics("s", "test", "calls", "all", now, end, 100, 90, 10)
    monkeypatch.setattr("autolycus.job.collect", good)
    assert "发送成功" in run_scheduled(config, now + timedelta(hours=1))


def test_status_accounts_for_shutdown_gap(config):
    begin_tracking(config, date("2026-11-13T09:00"))
    result = status_report(config, now=date("2026-11-13T12:00"))
    assert "计划次数：3" in result
    assert "未执行/漏报：3" in result


@pytest.mark.skipif(os.name != "nt", reason="Windows DPAPI integration")
def test_dpapi_roundtrip_and_env_precedence(tmp_path, monkeypatch):
    values = {name: f"test-sensitive-{index}" for index, name in enumerate(NAMES)}
    path = tmp_path / "credentials.dpapi"
    save_credentials(path, values)
    assert b"test-sensitive" not in path.read_bytes()
    assert read_credentials(path) == values
    for name in NAMES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv(NAMES[0], "explicit-override")
    load_credentials(path)
    assert os.environ[NAMES[0]] == "explicit-override"
    assert os.environ[NAMES[2]] == values[NAMES[2]]
    # Corruption must fail without returning plaintext.
    path.write_bytes(b"not-a-dpapi-blob")
    with pytest.raises(ValueError, match="凭据读取失败"):
        read_credentials(path)


def test_migration_preserves_existing_history(config):
    path = config["storage"]["path"]
    connection = sqlite3.connect(path)
    connection.executescript("""
        CREATE TABLE metrics (site TEXT, source TEXT, scope TEXT, start TEXT, end TEXT, payload TEXT, assessment TEXT,
                              PRIMARY KEY (site, source, scope, start, end));
        CREATE TABLE runs (id INTEGER PRIMARY KEY, created_at TEXT DEFAULT CURRENT_TIMESTAMP, status TEXT, detail TEXT);
        CREATE TABLE notifications (key TEXT PRIMARY KEY, status TEXT, updated_at TEXT DEFAULT CURRENT_TIMESTAMP);
        INSERT INTO runs(status, detail) VALUES ('success', 'existing-record');
        PRAGMA user_version=1;
    """)
    connection.close()
    store = Store(path)
    try:
        assert store.db.execute("PRAGMA user_version").fetchone()[0] == 2
        assert store.db.execute("SELECT detail FROM runs").fetchone()[0] == "existing-record"
    finally:
        store.close()
