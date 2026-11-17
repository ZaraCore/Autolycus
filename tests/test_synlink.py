from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

import httpx
import pytest

from autolycus.collector import collect
from autolycus.config import load_config
from autolycus.report import render
from autolycus.rules import assess
from autolycus.storage import Store


def test_synlink_supplied_response_and_exact_query(monkeypatch, tmp_path):
    config = load_config("tests/fixtures/site_config.toml")
    # Regression coverage for the previously verified rolling endpoint.
    config["query"] = {"mode": "relative", "range": "1h", "filters": {}}
    payload = json.loads(Path("tests/fixtures/synlink_summary.json").read_text())
    monkeypatch.setenv("AUTOLYCUS_ACCESS_TOKEN", "local-test-token")
    def handler(request):
        assert request.url.path == "/api/metrics/query"
        assert dict(request.url.params) == {"range": "1h"}
        assert request.headers["Authorization"] == "Bearer local-test-token"
        return httpx.Response(200, json=payload)
    end = datetime.now(timezone(timedelta(hours=8)))
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        metrics = collect(config, end - timedelta(hours=1), end, client)
    assert metrics.total == 100945
    assert metrics.success_rate == pytest.approx(47818 / 100945)
    assert metrics.p95_seconds == pytest.approx(201.21469090909073)
    assert metrics.latency_samples == 76952
    assert metrics.window_kind == "relative"
    assert metrics.end - metrics.start == timedelta(hours=1)
    assessment = assess(metrics, config["rules"])
    assert assessment.status == "异常"
    report = render(metrics, assessment)
    assert "滚动统计" in report
    assert "Autolycus 巡检" in report
    assert "成功率：" not in report
    store = Store(tmp_path / "history.db")
    try:
        store.save(metrics, assessment)
        assert store.baseline(metrics, config["rules"]) is None
    finally:
        store.close()
