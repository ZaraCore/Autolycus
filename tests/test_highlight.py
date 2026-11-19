from datetime import datetime, timedelta

import httpx
import pytest

from autolycus.channel_monitor import render_monitor
from autolycus.config import load_config
from autolycus.highlight import latency, settings, success
from autolycus.model_performance import supplement_models
from autolycus.schedule import BEIJING


@pytest.mark.parametrize("count,expected", [
    (0, "red"), (6999, "red"), (7000, "orange"), (9499, "orange"),
    (9500, None), (9501, "green"), (10000, "green")])
def test_success_boundaries(count, expected):
    result = success("rate", count, 10000)
    assert result == (f"<font color='{expected}'>rate</font>" if expected else "rate")
    assert success("无调用", 0, 0) == "无调用"


@pytest.mark.parametrize("percentile,limit", [("p50", 60), ("p95", 120)])
def test_latency_boundaries_and_missing_data(percentile, limit):
    assert latency("value", limit, percentile) == "value"
    assert latency("value", limit + .01, percentile) == "<font color='orange'>value</font>"
    assert latency("value", limit * 2, percentile) == "<font color='orange'>value</font>"
    assert latency("value", limit * 2 + .01, percentile) == "<font color='red'>value</font>"
    assert latency("无数据", None, percentile) == "<font color='red'>无数据</font>"


def test_custom_thresholds_and_disable():
    config = {"highlight": {"success_red_below": 80, "p50_orange_above_seconds": 20}}
    assert "red" in success("75%", 75, 100, config)
    assert "orange" in latency("p50(30s)", 30, "p50", config)
    config["highlight"]["enabled"] = False
    assert success("75%", 75, 100, config) == "75%"
    assert latency("p50(90s)", 90, "p50", config) == "p50(90s)"


@pytest.mark.parametrize("options", [
    {"enabled": "yes"}, {"success_red_below": 96}, {"success_orange_below": 101},
    {"p50_orange_above_seconds": 0}, {"p95_orange_above_seconds": float("nan")},
    {"latency_red_multiplier": 1}, {"success_red_below": True}])
def test_invalid_settings(options):
    with pytest.raises(ValueError):
        settings({"highlight": options})


def test_config_loader_validates_highlight(tmp_path):
    path = tmp_path / "config.toml"
    from pathlib import Path
    path.write_text(Path("config.example.toml").read_text(encoding="utf-8")
                    + '\n[highlight]\nenabled = "yes"\n', encoding="utf-8")
    with pytest.raises(ValueError, match="highlight.enabled"):
        load_config(path)


def test_channel_colors_only_percentage_and_escapes_names():
    start = datetime(2026, 11, 19, 10, tzinfo=BEIJING)
    data = {"dimension": "channel", "start": int(start.timestamp()),
            "end": int((start + timedelta(hours=1)).timestamp()),
            "rows": [{"key": "210", "name": "<font>name", "success": 90,
                      "total": 100, "failure": 10, "errors": [("400", 10)]}]}
    report = render_monitor(data, start, start + timedelta(hours=1))
    assert "| (#210) **&lt;font&gt;name** | <font color='orange'>90%</font> | 90/100 | 400(10) |" in report
    assert report.count("<font ") == 1


def test_model_colors_each_latency_and_failure_separately(monkeypatch):
    config = load_config("tests/fixtures/site_config.toml")
    config["model_performance"]["targets"] = [
        {"group": "Banana", "model": "slow"}, {"group": "Banana", "model": "broken"}]
    monkeypatch.setenv("AUTOLYCUS_ACCESS_TOKEN", "test")
    def handler(request):
        if request.url.params["model_name"] == "broken":
            return httpx.Response(403)
        return httpx.Response(200, json={"data": {"total": 100, "success": 100, "failure": 0,
            "duration_count": 100, "quantiles": {"p50": 61, "p95": 241}}})
    start = datetime(2026, 11, 19, 10, tzinfo=BEIJING)
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        report = supplement_models(config, start, start + timedelta(hours=1), client)
    assert "| **slow** | 100 | <font color='orange'>61s</font> | <font color='red'>241s</font> |" in report
    assert "| **broken** | <font color='red'>数据不可用" in report
