import json
from datetime import datetime, timedelta
from pathlib import Path

import httpx
import pytest

from autolycus.feishu import NotificationError, send
from autolycus.markdown import table, table_count


@pytest.mark.parametrize("number", [0, 1, 3, 4, 5, 6])
def test_card_table_limit_checked_before_network(monkeypatch, number):
    monkeypatch.setenv("AUTOLYCUS_FEISHU_WEBHOOK", "https://open.feishu.cn/open-apis/bot/v2/hook/test")
    body = "\n\n".join(table(["名称", "值"], [["测试", "90%"]]) for _ in range(number))
    calls = []
    def handler(request):
        payload = json.loads(request.content)
        calls.append(payload)
        assert payload["card"]["body"]["elements"][0]["content"] == body
        return httpx.Response(200, json={"code": 0})
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        if number > 4:
            with pytest.raises(NotificationError, match="最多支持4张"):
                send(body, client)
            assert not calls
        else:
            send(body, client)
            assert len(calls) == 1


def test_business_error_reports_codes_without_exposing_upstream_body(monkeypatch):
    monkeypatch.setenv("AUTOLYCUS_FEISHU_WEBHOOK", "https://open.feishu.cn/open-apis/bot/v2/hook/test")
    message = "ErrCode: 11310; ErrMsg: card table number over limit; secret-token private-url"
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(
            200, json={"code": 11246, "msg": message}))) as client:
        with pytest.raises(NotificationError) as error:
            send("report", client)
    assert "11246" in str(error.value) and "11310" in str(error.value)
    assert "表格数量" in str(error.value)
    assert "secret-token" not in str(error.value) and "private-url" not in str(error.value)


def test_plain_text_pipes_and_escaped_names_are_not_extra_tables():
    body = "text | values\n---\n" + table(["名称"], [[r"name\|other"]])
    assert table_count(body) == 1


def test_full_report_with_four_model_groups_has_only_three_tables(monkeypatch):
    from autolycus.channel_monitor import parse, render_monitor
    from autolycus.config import load_config
    from autolycus.model_performance import supplement_models
    from autolycus.schedule import BEIJING
    config = load_config("tests/fixtures/site_config.toml")
    monkeypatch.setenv("AUTOLYCUS_ACCESS_TOKEN", "test")
    monkeypatch.setenv("AUTOLYCUS_FEISHU_WEBHOOK", "https://open.feishu.cn/open-apis/bot/v2/hook/test")
    start = datetime(2026, 11, 19, 14, tzinfo=BEIJING)
    end = start + timedelta(hours=1)
    sections = ["# 巡检"]
    for dimension in ("channel", "group"):
        source = json.loads(Path(f"tests/fixtures/{dimension}_monitor.json").read_text(encoding="utf-8"))
        sections.append(render_monitor(parse(source, dimension), start, end, config))
    calls = []
    def handler(request):
        if request.method == "GET":
            return httpx.Response(200, json=json.loads(Path("tests/fixtures/model_success_summary.json").read_text(encoding="utf-8")))
        content = json.loads(request.content)["card"]["body"]["elements"][0]["content"]
        assert table_count(content) == 3
        assert content.count("| 分组 | 模型 | 成功次数 | P50 | P95 |") == 1
        for group in ("OpenAI", "OpenAI 官key", "Banana", "Gemini官key"):
            assert f"| **{group}** |" in content
        calls.append(content)
        return httpx.Response(200, json={"code": 0})
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        sections.append(supplement_models(config, start, end, client))
        send("\n\n".join(sections), client)
    assert len(calls) == 1
