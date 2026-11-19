import json
from datetime import datetime, timedelta
from pathlib import Path

import httpx
import pytest

from autolycus.channel_monitor import parse, render_monitor, collect_monitor, supplement
from autolycus.collector import CollectionError
from autolycus.config import load_config
from autolycus.schedule import BEIJING
from autolycus.markdown import escape


def fixture(dimension):
    return json.loads(Path(f"tests/fixtures/{dimension}_monitor.json").read_text(encoding="utf-8"))


def test_supplied_channels_sort_top20_errors():
    data = parse(fixture("channel"), "channel")
    assert len(data["rows"]) == 43
    assert data["rows"] == sorted(data["rows"], key=lambda row: (-row["total"], row["key"]))
    original = fixture("channel")["data"]["rows"]
    assert sum(row["total"] for row in data["rows"]) == sum(b["consume"]+b["error"] for r in original for b in r["buckets"])
    row = next(row for row in data["rows"] if row["key"] == "387")
    assert row["errors"] == [("400", 273), ("503", 157), ("500", 1)]
    start = datetime.fromtimestamp(data["start"], BEIJING)
    report = render_monitor(data, start, start + timedelta(hours=1), {"highlight": {"enabled": False}})
    assert sum(line.startswith("(#") for line in report.splitlines()) == 20
    assert "| ---" not in report


def test_groups_below_95_keep_original_relative_order():
    data = parse(fixture("group"), "group")
    assert len(data["rows"]) == 20
    report = render_monitor(data, datetime(2026,11,16,10,tzinfo=BEIJING), datetime(2026,11,16,11,tzinfo=BEIJING), {"highlight": {"enabled": False}})
    assert "范围提示" not in report
    assert "重试聚合" in report
    expected = [row for row in data["rows"] if row["total"] > 0 and row["success"] * 100 < row["total"] * 95]
    from autolycus.markdown import escape
    assert [line for line in report.splitlines()[4:] if line] == [
        f"{escape(row['name'])} - {format(row['success']/row['total']*100, '.2f').rstrip('0').rstrip('.')}% ({row['success']}/{row['total']})" for row in expected]


def test_group_threshold_is_strict_and_uses_unrounded_counts():
    data = {"dimension": "group", "start": 1794798000, "end": 1794801600,
            "rows": [dict(name="exact95", success=95, total=100),
                     dict(name="below95", success=94999, total=100000),
                     dict(name="empty", success=0, total=0),
                     dict(name="zero", success=0, total=1)]}
    start = datetime.fromtimestamp(data["start"], BEIJING)
    report = render_monitor(data, start, start + timedelta(hours=1), {"highlight": {"enabled": False}})
    assert "exact95" not in report and "empty" not in report
    assert report.index("below95") < report.index("zero")


def test_channel_row_matches_reference_punctuation_and_numbers():
    data = {"dimension": "channel", "start": 1794798000, "end": 1794801600,
            "rows": [dict(key="210", name="朱老板-image-2.5-base", success=9000,
                          total=10000, failure=1000,
                          errors=[("400", 500), ("451", 300), ("429", 200)])]}
    start = datetime.fromtimestamp(data["start"], BEIJING)
    report = render_monitor(data, start, start + timedelta(hours=1), {"highlight": {"enabled": False}})
    assert report.splitlines()[4:] == [
        f"(#210) {escape('朱老板-image-2.5-base')} - 90% (9000/10000): 400(500), 451(300), 429(200)"]


def test_group_row_matches_reference_format_and_preserves_filter():
    data = {"dimension": "group", "start": 1794798000, "end": 1794801600,
            "rows": [dict(name="OpenAI", success=9000, total=10000),
                     dict(name="Hidden99", success=9900, total=10000)]}
    start = datetime.fromtimestamp(data["start"], BEIJING)
    report = render_monitor(data, start, start + timedelta(hours=1), {"highlight": {"enabled": False}})
    assert report.splitlines()[4:] == ["OpenAI - 90% (9000/10000)"]


@pytest.mark.parametrize("dimension", ["channel", "group"])
def test_requests_match_browser(dimension, monkeypatch):
    config = load_config("tests/fixtures/site_config.toml")
    monkeypatch.setenv("AUTOLYCUS_ACCESS_TOKEN", "test-token")
    def handler(request):
        assert request.method == "POST"
        assert request.url.path == "/channel_monitor"
        assert request.url.params["Action"] == "Query"
        body = json.loads(request.content)
        assert body["range_sec"] == 54000
        assert body["window_sec"] == 300
        assert body["dimension"] == dimension
        if dimension == "group":
            assert body["aggregate_retries"] is True and body["groups"] == []
        else:
            assert body["include_error_distribution"] is True and body["channel_ids"] == []
        return httpx.Response(200, json=fixture(dimension))
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        assert collect_monitor(config, dimension, 54000, client)["dimension"] == dimension


def test_bad_payload_never_silently_normal():
    bad = fixture("channel")
    bad["data"]["rows"][0]["buckets"][0]["consume"] = -1
    with pytest.raises(CollectionError):
        parse(bad, "channel")
    with pytest.raises(CollectionError):
        parse(fixture("group"), "channel")


def test_partial_failure_keeps_other_section(monkeypatch):
    config = load_config("tests/fixtures/site_config.toml")
    def collect(config, dimension, duration):
        if dimension == "channel":
            raise CollectionError("401")
        return parse(fixture("group"), "group")
    monkeypatch.setattr("autolycus.channel_monitor.collect_monitor", collect)
    start = datetime(2026,11,16,10,tzinfo=BEIJING)
    text = supplement(config, start, start + timedelta(hours=1))
    assert "分渠道：数据不可用" in text
    assert "分组成功率" in text
