from datetime import datetime, timedelta
import json
from pathlib import Path
import sqlite3
import sys
import types

import pytest

from autolycus.config import load_config
from autolycus.daemon import eligible, preflight
from autolycus.maintenance import backup_database, heartbeat, healthy
from autolycus.schedule import BEIJING, slot_key
from autolycus.storage import Store


@pytest.fixture
def config(tmp_path):
    result = load_config("config/deployment.example.toml")
    result["site"]["base_url"] = "https://backend.test"
    result["storage"]["path"] = str(tmp_path / "history.db")
    return result


def test_env_override_preserves_config_file(monkeypatch, tmp_path):
    source = Path("config/deployment.example.toml")
    before = source.read_bytes()
    monkeypatch.setenv("AUTOLYCUS_BASE_URL", "https://another.test")
    monkeypatch.setenv("AUTOLYCUS_SITE_NAME", "Another service")
    monkeypatch.setenv("AUTOLYCUS_DATABASE", str(tmp_path / "data.db"))
    result = load_config(source)
    assert result["site"]["base_url"] == "https://another.test"
    assert result["site"]["name"] == "Another service"
    assert source.read_bytes() == before


def test_online_backup_includes_wal_but_not_uncommitted_data(tmp_path):
    source, output = tmp_path / "live.db", tmp_path / "backup.db"
    writer = sqlite3.connect(source)
    try:
        writer.execute("PRAGMA journal_mode=WAL")
        writer.execute("CREATE TABLE entries(value)")
        writer.execute("INSERT INTO entries VALUES ('committed')")
        writer.commit()
        writer.execute("INSERT INTO entries VALUES ('pending')")
        backup_database(source, output)
        with sqlite3.connect(output) as restored:
            assert restored.execute("SELECT value FROM entries").fetchall() == [("committed",)]
        with pytest.raises(ValueError):
            backup_database(source, output)
    finally:
        writer.close()


def test_missing_database_does_not_create_empty_backup(tmp_path):
    with pytest.raises(ValueError):
        backup_database(tmp_path / "absent.db", tmp_path / "copy.db")
    assert not (tmp_path / "copy.db").exists()


def test_health_distinguishes_stale_or_stopped_process(tmp_path):
    path = tmp_path / "heartbeat.json"
    heartbeat(path, state="working")
    assert healthy(path)
    heartbeat(path, state="stopped")
    assert not healthy(path)
    path.write_text(json.dumps({"timestamp": 0, "state": "idle"}))
    assert not healthy(path)


def test_preflight_rejects_missing_secrets_or_placeholder(config, monkeypatch):
    monkeypatch.delenv("AUTOLYCUS_ACCESS_TOKEN", raising=False)
    with pytest.raises(ValueError):
        preflight(config)
    monkeypatch.setenv("AUTOLYCUS_ACCESS_TOKEN", "test")
    monkeypatch.setenv("AUTOLYCUS_FEISHU_WEBHOOK", "test")
    preflight(config)
    config["site"]["base_url"] = "https://backend.example.com"
    with pytest.raises(ValueError):
        preflight(config)


def test_eligible_avoids_duplicate_and_waits_for_crash_lease(config):
    now = datetime(2026,11,17,9,tzinfo=BEIJING)
    key = slot_key(config, now)
    assert eligible(config, now, {}) == key
    store = Store(config["storage"]["path"])
    try:
        assert store.claim_slot(key, now, now)
        assert eligible(config, now + timedelta(minutes=2), {}) is None
        assert eligible(config, now + timedelta(minutes=5), {}) == key
        store.finish_slot(key, "sent", now, "ok")
        assert eligible(config, now + timedelta(minutes=6), {}) is None
    finally:
        store.close()
    assert eligible(config, now.replace(hour=20), {}) is None


def test_release_allowlist_excludes_local_configuration_and_history():
    import importlib.util
    spec = importlib.util.spec_from_file_location("prepare_source", "scripts/prepare-source.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    names = {p.relative_to(module.ROOT).as_posix() for p in module.source_files()}
    assert "config.synlink.toml" not in names
    assert "scripts/manage-task.ps1" not in names
    assert ".env" not in names and "config.toml" not in names
    assert not any("/local/" in p or p.startswith("data/") for p in names)
    assert "compose.yaml" in names and "scripts/linux/deploy.sh" in names
    assert "tests/fixtures/site_config.toml" in names
