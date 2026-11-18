import json
from datetime import datetime, timedelta

import httpx

from autolycus.config import load_config
from autolycus.feishu import send
from autolycus.markdown import escape
from autolycus.models import Metrics
from autolycus.schedule import BEIJING
from autolycus.scheduled import run_scheduled
from autolycus.storage import Store


def test_markdown_source_is_sent_in_static_card_unchanged(monkeypatch):
    monkeypatch.setenv("AUTOLYCUS_FEISHU_WEBHOOK", "https://open.feishu.cn/open-apis/bot/v2/hook/test")
    source = "# 巡检\n\n| 渠道 | 成功率 |\n| --- | --- |\n| 测试 | 90% |\n\n- **模型**：P50 1.0秒"
    def handler(request):
        payload = json.loads(request.content)
        assert payload["msg_type"] == "interactive"
        assert payload["card"]["schema"] == "2.0"
        assert payload["card"]["body"]["elements"] == [{"tag": "markdown", "content": source}]
        assert "content" not in payload
        return httpx.Response(200, json={"code": 0})
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        send(source, client)


def test_scheduled_markdown_cache_matches_sent_source(monkeypatch, tmp_path):
    config = load_config("tests/fixtures/site_config.toml")
    config["storage"]["path"] = str(tmp_path / "report.db")
    slot = datetime(2026, 11, 18, 10, tzinfo=BEIJING)
    metrics = Metrics("site", "站点", "calls", "scope", slot-timedelta(hours=1), slot, 100, 90, 10)
    monkeypatch.setattr("autolycus.job.collect", lambda *args: metrics)
    monkeypatch.setattr("autolycus.job.supplement", lambda *args: "\n\n## 渠道成功率\n\n无记录")
    monkeypatch.setattr("autolycus.job.supplement_models", lambda *args: "\n\n## 重点模型延迟\n\n无记录")
    sent = []
    monkeypatch.setattr("autolycus.job.send", sent.append)
    run_scheduled(config, slot)
    assert sent[0].startswith("# Autolycus 巡检\n\n- 计划时间：")
    assert "\n- 站点：站点\n- 时段：" in sent[0]
    assert "通知：" not in sent[0]
    store = Store(config["storage"]["path"])
    try:
        assert store.db.execute("SELECT report FROM scheduled_runs").fetchone()[0] == sent[0]
    finally:
        store.close()


def test_dynamic_text_cannot_break_markdown_structure():
    assert escape("name|other\n# heading") == "name\\|other \\# heading"
    assert escape("[link](url) <tag> *bold*") == "\\[link\\]\\(url\\) &lt;tag&gt; \\*bold\\*"
