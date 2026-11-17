from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import base64
import json

import httpx
import pytest

from autolycus.collector import CollectionError, collect, normalize, scope_key
from autolycus.config import load_config
from autolycus.feishu import NotificationError, send
from autolycus.job import execute
from autolycus.models import Metrics
from autolycus.rules import assess
from autolycus.storage import Store

START = datetime(2026, 11, 13, 9, tzinfo=timezone(timedelta(hours=8)))
END = START + timedelta(hours=1)


@pytest.fixture
def config(tmp_path):
    result = load_config("config.example.toml")
    result["site"].update(base_url="https://backend.test", metrics_path="/api/metrics")
    result["storage"]["path"] = str(tmp_path / "history.db")
    return result


def metric(total=1000, success=900, start=START, **kwargs):
    return Metrics("site", "测试", "production", "all-v1", start, start + timedelta(hours=1),
                   total, success, total - success, **kwargs)


def test_rules_cover_thresholds_and_unknown_data(config):
    rules = config["rules"]
    assert assess(metric(), rules).status == "正常"
    assert assess(metric(success=650), rules).status == "异常"
    assert assess(metric(success=800), rules, baseline=.95).status == "异常"
    assert assess(metric(total=0, success=0), rules).status == "无调用"
    assert assess(metric(total=3, success=1), rules).status == "待观察"
    assert assess(metric(success=700), rules).status == "正常"


@pytest.mark.parametrize("kwargs", [{"total": True}, {"success": -1}, {"failure": 50},
                                        {"p50_seconds": float("nan")}, {"p95_seconds": -1},
                                        {"p50_seconds": 100, "p95_seconds": 10},
                                        {"latency_samples": 2000}])
def test_invalid_metrics_rejected(kwargs):
    values = dict(site_id="a", site_name="A", source="calls", scope="all", start=START, end=END,
                  total=1000, success=900, failure=100)
    values.update(kwargs)
    with pytest.raises(ValueError):
        Metrics(**values)


def test_collect_with_real_http_contract(config, monkeypatch):
    monkeypatch.setenv("AUTOLYCUS_ACCESS_TOKEN", "test-secret")
    monkeypatch.setenv("AUTOLYCUS_USER_ID", "42")
    def handler(request):
        assert request.method == "GET"
        assert request.headers["Authorization"] == "Bearer test-secret"
        assert request.headers["New-Api-User"] == "42"
        assert int(request.url.params["start_timestamp"]) == int(START.timestamp())
        return httpx.Response(200, json={"success": True, "data": {"total": 1000, "success_count": 650, "failure_count": 350}})
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = collect(config, START, END, client)
    assert result.success_rate == .65
    assert result.p95_seconds is None


@pytest.mark.parametrize("payload", [{"success": False}, {"data": {}},
    {"data": {"total": 100, "success_count": 70, "failure_count": 40}}])
def test_bad_payload_never_becomes_zero_or_normal(config, payload):
    with pytest.raises(CollectionError):
        normalize(payload, config, START, END)


def test_filters_isolate_baselines(config):
    before = scope_key(config)
    config["query"]["filters"] = {"group": "OpenAI"}
    assert scope_key(config) != before


def test_http_error_does_not_expose_credentials(config, monkeypatch):
    monkeypatch.setenv("AUTOLYCUS_ACCESS_TOKEN", "private-token")
    def handler(request):
        return httpx.Response(401, json={"message": "private-token"})
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(CollectionError) as error:
            collect(config, START, END, client)
    assert "401" in str(error.value)
    assert "private-token" not in str(error.value)


def test_missing_credentials_fails_without_network(config, monkeypatch):
    monkeypatch.delenv("AUTOLYCUS_ACCESS_TOKEN", raising=False)
    with pytest.raises(CollectionError, match="AUTOLYCUS_ACCESS_TOKEN"):
        collect(config, START, END)


def test_storage_upsert_and_weighted_same_hour_baseline(config):
    store = Store(config["storage"]["path"])
    rules = config["rules"]
    try:
        a = metric(total=1000, success=900, start=START - timedelta(days=1))
        b = metric(total=100, success=50, start=START - timedelta(days=2))
        for item in (a, b, a):
            store.save(item, assess(item, rules))
        assert store.db.execute("SELECT COUNT(*) FROM metrics").fetchone()[0] == 2
        assert store.baseline(metric(), rules) == pytest.approx(950 / 1100)
        assert store.baseline(metric(start=START + timedelta(hours=1)), rules) is None
    finally:
        store.close()


def test_feishu_signature_and_business_error(monkeypatch):
    monkeypatch.setenv("AUTOLYCUS_FEISHU_WEBHOOK", "https://open.feishu.cn/open-apis/bot/v2/hook/test")
    monkeypatch.setenv("AUTOLYCUS_FEISHU_SECRET", "secret")
    def handler(request):
        payload = json.loads(request.content)
        expected = base64.b64encode(hmac.new(f"{payload['timestamp']}\nsecret".encode(), b"", hashlib.sha256).digest()).decode()
        assert payload["sign"] == expected
        return httpx.Response(200, json={"code": 19024, "msg": "keyword rejected"})
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(NotificationError):
            send("测试报告", client)


def test_job_preview_and_notification_dedup(config, monkeypatch):
    assert "【演示数据】" in execute(config, START, END, demo="normal")
    config["notification"]["enabled"] = True
    calls = []
    monkeypatch.setattr("autolycus.job.send", lambda report: calls.append(report))
    assert "飞书发送成功" in execute(config, START, END, demo="abnormal", notify=True)
    assert "已跳过" in execute(config, START, END, demo="abnormal", notify=True)
    assert len(calls) == 1
    execute(config, START, END, demo="abnormal", notify=True, force=True)
    assert len(calls) == 2


def test_failed_notification_can_retry(config, monkeypatch):
    config["notification"]["enabled"] = True
    def fail(report):
        raise NotificationError("模拟失败")
    monkeypatch.setattr("autolycus.job.send", fail)
    with pytest.raises(NotificationError):
        execute(config, START, END, demo="normal", notify=True)
    monkeypatch.setattr("autolycus.job.send", lambda report: None)
    assert "飞书发送成功" in execute(config, START, END, demo="normal", notify=True)
