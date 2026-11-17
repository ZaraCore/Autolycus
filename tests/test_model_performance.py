from copy import deepcopy
from datetime import datetime
import json
from pathlib import Path

import httpx
import pytest

from autolycus.collector import CollectionError, normalize
from autolycus.config import load_config
from autolycus.model_performance import latency_line, supplement_models, target_config
from autolycus.schedule import BEIJING

START = datetime(2026, 11, 16, 11, tzinfo=BEIJING)
END = datetime(2026, 11, 16, 12, tzinfo=BEIJING)


def sample():
    return json.loads(Path("tests/fixtures/model_success_summary.json").read_text(encoding="utf-8"))


def test_success_filter_request_and_grouped_output(monkeypatch):
    config = load_config("tests/fixtures/site_config.toml")
    config["model_performance"]["targets"] = [{"group": "OpenAI", "model": "gpt-image-2.5-sunburst"}]
    original = deepcopy(config)
    monkeypatch.setenv("AUTOLYCUS_ACCESS_TOKEN", "test-token")
    def handler(request):
        assert dict(request.url.params) == {
            "range": "custom", "group": "OpenAI", "model_name": "gpt-image-2.5-sunburst",
            "log_type": "2", "start": "1794798000", "end": "1794801600"}
        return httpx.Response(200, json=sample())
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        text = supplement_models(config, START, END, client)
    assert "OpenAI分组" in text
    assert "成功3,137次｜P50 39.2秒｜P95 78.5秒" in text
    assert "耗时样本" not in text
    assert "不代表异步任务最终完成" not in text
    assert config == original


def test_failure_records_rejected():
    config = load_config("tests/fixtures/site_config.toml")
    payload = sample()
    payload["data"].update(total=3138, failure=1)
    metrics = normalize(payload, config, START, END)
    with pytest.raises(CollectionError, match="筛选未生效"):
        latency_line(metrics, "model")


def test_zero_success_is_omitted_and_missing_samples_are_explicit():
    config = load_config("tests/fixtures/site_config.toml")
    payload = sample()
    payload["data"].update(total=0, success=0, failure=0, duration_count=0)
    assert latency_line(normalize(payload, config, START, END), "model") is None
    payload["data"].update(total=10, success=10)
    assert "无有效耗时样本" in latency_line(normalize(payload, config, START, END), "model")


def test_one_target_failure_preserves_others(monkeypatch):
    config = load_config("tests/fixtures/site_config.toml")
    config["model_performance"]["targets"].append({"group": "OpenAI 官key", "model": "confirmed-model"})
    monkeypatch.setenv("AUTOLYCUS_ACCESS_TOKEN", "test")
    def handler(request):
        if request.url.params["group"] == "OpenAI":
            return httpx.Response(403)
        return httpx.Response(200, json=sample())
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        text = supplement_models(config, START, END, client)
    assert "数据不可用" in text and "OpenAI 官key分组" in text and "成功3,137次" in text


def test_relative_query_cannot_be_relabelled_fixed():
    config = load_config("tests/fixtures/site_config.toml")
    config["query"]["mode"] = "relative"
    with pytest.raises(CollectionError):
        target_config(config, config["model_performance"]["targets"][0])


def test_all_seventeen_configured_targets_are_queried(monkeypatch):
    config = load_config("tests/fixtures/site_config.toml")
    targets = config["model_performance"]["targets"]
    assert len(targets) == 17
    assert [sum(t["group"] == group for t in targets) for group in ("OpenAI", "OpenAI 官key", "Gemini官key")] == [5, 5, 7]
    seen = []
    monkeypatch.setenv("AUTOLYCUS_ACCESS_TOKEN", "test-token")
    def handler(request):
        assert request.url.params["log_type"] == "2"
        seen.append((request.url.params["group"], request.url.params["model_name"]))
        return httpx.Response(200, json=sample())
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        report = supplement_models(config, START, END, client)
    assert seen == [(t["group"], t["model"]) for t in targets]
    assert all(f"{group}分组" in report for group in ("OpenAI", "OpenAI 官key", "Gemini官key"))
