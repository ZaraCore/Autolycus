from datetime import datetime, timedelta, timezone
from pathlib import Path
import tomllib

import pytest

from autolycus.schedule import BEIJING, due_slot, inspection_window, slots_between
from autolycus.config import load_config
from autolycus.collector import collect
from autolycus.scheduled import run_scheduled
import httpx
import json


@pytest.fixture
def config():
    return tomllib.loads(Path("schedule.requirements.toml").read_text(encoding="utf-8"))


def at(text):
    return datetime.fromisoformat(text).replace(tzinfo=BEIJING)


def test_new_schedule_week_has_56_reports(config):
    slots = slots_between(config, at("2026-11-16T00:00"), at("2026-11-22T23:59"))
    assert len(slots) == 56
    assert all(slot.minute == 0 for slot in slots)
    assert [slot.hour for slot in slots if slot.weekday() == 0] == list(range(9, 19))
    assert [slot.hour for slot in slots if slot.weekday() == 5] == [9, 12, 18]


@pytest.mark.parametrize("start,end", [
    ("2026-11-20T18:00", "2026-11-21T09:00"),
    ("2026-11-21T09:00", "2026-11-21T12:00"),
    ("2026-11-21T12:00", "2026-11-21T18:00"),
    ("2026-11-21T18:00", "2026-11-22T09:00"),
    ("2026-11-22T09:00", "2026-11-22T12:00"),
    ("2026-11-22T18:00", "2026-11-23T09:00"),
    ("2026-11-18T13:00", "2026-11-18T14:00"),
])
def test_continuous_windows(config, start, end):
    assert inspection_window(config, at(end)) == (at(start), at(end))


def test_delayed_execution_keeps_planned_bounds(config):
    slot = due_slot(config, at("2026-11-21T12:04"))
    assert inspection_window(config, slot) == (at("2026-11-21T09:00"), at("2026-11-21T12:00"))


def test_invalid_slot_rejected_and_timezone_converted(config):
    with pytest.raises(ValueError):
        inspection_window(config, at("2026-11-21T10:00"))
    utc = datetime(2026, 11, 18, 6, tzinfo=timezone.utc)
    assert inspection_window(config, utc) == (at("2026-11-18T13:00"), at("2026-11-18T14:00"))


def test_live_configuration_matches_approved_candidate(config):
    live = load_config("tests/fixtures/site_config.toml")
    assert live["schedule"]["weekday_times"] == config["schedule"]["weekday_times"]
    assert live["schedule"]["weekend_times"] == config["schedule"]["weekend_times"]
    assert live["schedule"]["interval_mode"] == "planned_chain"


def test_custom_endpoint_sends_confirmed_seconds(monkeypatch):
    live = load_config("tests/fixtures/site_config.toml")
    monkeypatch.setenv("AUTOLYCUS_ACCESS_TOKEN", "test-token")
    payload = json.loads(Path("tests/fixtures/synlink_summary.json").read_text())
    def handler(request):
        assert dict(request.url.params) == {"range": "custom", "start": "1794790800", "end": "1794794400"}
        return httpx.Response(200, json=payload)
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = collect(live, at("2026-11-16T09:00"), at("2026-11-16T10:00"), client)
    assert result.window_kind == "absolute"
    assert result.start == at("2026-11-16T09:00")
    assert result.end == at("2026-11-16T10:00")


def test_scheduled_weekend_uses_15_hour_interval(monkeypatch, tmp_path):
    live = load_config("tests/fixtures/site_config.toml")
    live["storage"]["path"] = str(tmp_path / "schedule.db")
    received = []
    monkeypatch.setattr("autolycus.scheduled.execute", lambda cfg, start, end, **kw: received.append((start, end)) or "test-report")
    run_scheduled(live, at("2026-11-21T09:04"))
    assert received == [(at("2026-11-20T18:00"), at("2026-11-21T09:00"))]
