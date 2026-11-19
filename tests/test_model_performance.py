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
from autolycus.markdown import escape

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
    assert "(OpenAI: 3137): p50(39.2s), p95(78.5s)" in text
    assert "### OpenAI分组：" in text and "**" not in text
    assert "成功3,137次" not in text
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


@pytest.mark.parametrize("group,count,p50,p95", [("OpenAI", 8000, 50, 100), ("OpenAI 官key", 800, 40, 80)])
def test_latency_row_matches_reference(group, count, p50, p95):
    config = load_config("tests/fixtures/site_config.toml")
    payload = sample()
    payload["data"].update(total=count, success=count, duration_count=count,
                           quantiles={"p50": p50, "p95": p95})
    metrics = normalize(payload, config, START, END)
    assert latency_line(metrics, "gpt-image-2", group) == (
        f"{escape('gpt-image-2')}({group}: {count}): p50({p50}s), p95({p95}s)")


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
    assert "数据不可用" in text and "(OpenAI 官key: 3137): p50(39.2s), p95(78.5s)" in text


def test_relative_query_cannot_be_relabelled_fixed():
    config = load_config("tests/fixtures/site_config.toml")
    config["query"]["mode"] = "relative"
    with pytest.raises(CollectionError):
        target_config(config, config["model_performance"]["targets"][0])


def test_banana_only_displays_models_with_successful_calls(monkeypatch):
    config = load_config("tests/fixtures/site_config.toml")
    config["model_performance"]["targets"] = [
        target for target in config["model_performance"]["targets"]
        if target["group"] in ("Banana", "Gemini官key")]
    banana = [t["model"] for t in config["model_performance"]["targets"] if t["group"] == "Banana"]
    assert banana == ["gemini-2.5-flash-image", "gemini-3-pro-image", "gemini-3-pro-image-preview",
                      "gemini-3.1-flash-image", "gemini-3.1-flash-image-preview",
                      "gemini-3.1-flash-lite-image", "gemini-nano-banana-2.1"]
    monkeypatch.setenv("AUTOLYCUS_ACCESS_TOKEN", "test")
    seen = []
    def handler(request):
        pair = (request.url.params["group"], request.url.params["model_name"])
        seen.append(pair)
        payload = sample()
        if pair != ("Banana", "gemini-3-pro-image"):
            payload["data"].update(total=0, success=0, failure=0, duration_count=0)
        return httpx.Response(200, json=payload)
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        report = supplement_models(config, START, END, client)
    assert len(seen) == 14
    assert report == ("\n\n## 重点模型延迟｜消费日志（log_type=2）\n\n### Banana分组：\n\n"
                      + escape("gemini-3-pro-image") + "(Banana: 3137): p50(39.2s), p95(78.5s)")


def test_no_success_records_omit_all_group_headings(monkeypatch):
    config = load_config("tests/fixtures/site_config.toml")
    monkeypatch.setenv("AUTOLYCUS_ACCESS_TOKEN", "test")
    payload = sample()
    payload["data"].update(total=0, success=0, failure=0, duration_count=0)
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload))) as client:
        report = supplement_models(config, START, END, client)
    assert "###" not in report
    assert "均无成功消费记录" in report


def test_all_twenty_four_configured_targets_are_queried(monkeypatch):
    config = load_config("tests/fixtures/site_config.toml")
    targets = config["model_performance"]["targets"]
    assert len(targets) == 24
    assert [sum(t["group"] == group for t in targets) for group in ("OpenAI", "OpenAI 官key", "Banana", "Gemini官key")] == [5, 5, 7, 7]
    seen = []
    monkeypatch.setenv("AUTOLYCUS_ACCESS_TOKEN", "test-token")
    def handler(request):
        assert request.url.params["log_type"] == "2"
        seen.append((request.url.params["group"], request.url.params["model_name"]))
        return httpx.Response(200, json=sample())
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        report = supplement_models(config, START, END, client)
    assert seen == [(t["group"], t["model"]) for t in targets]
    assert all(f"({group}: 3137)" in report for group in ("OpenAI", "OpenAI 官key", "Banana", "Gemini官key"))

    assert [report.index(f"### {group}分组：") for group in ("OpenAI", "OpenAI 官key", "Banana", "Gemini官key")] == sorted(report.index(f"### {group}分组：") for group in ("OpenAI", "OpenAI 官key", "Banana", "Gemini官key"))
