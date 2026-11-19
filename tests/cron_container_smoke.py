"""Executed in the built Linux image by CI, with networking disabled."""
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time

from autolycus.maintenance import healthy


with tempfile.TemporaryDirectory() as directory:
    root = Path(directory)
    env = dict(os.environ, TZ="Asia/Shanghai")
    # Exercise the actual cron binary: job inherits env, runs as non-root,
    # produces output, and survives the read-only root filesystem.
    tab = root / "test.cron"
    output = root / "tick"
    tab.write_text(f"*/1 * * * * * * {sys.executable} -c 'import os; assert os.getuid() == 10001; print(os.environ[\"TZ\"])' >> {output}\n")
    cron = subprocess.Popen(["supercronic", str(tab)], env=env)
    try:
        for _ in range(100):
            if output.exists() and output.read_text().strip():
                break
            time.sleep(.1)
        assert output.read_text().strip().splitlines()[0] == "Asia/Shanghai"
    finally:
        cron.send_signal(signal.SIGTERM)
        cron.wait(timeout=10)
    # Exercise production entry point, generation, health, lock, graceful stop.
    hour = (datetime.now(timezone(timedelta(hours=8))).hour + 1) % 24
    config = root / "config.toml"
    source = Path("/test-config.toml").read_text()
    config.write_text(source.replace('path = "/var/lib/autolycus/autolycus.db"', f'path = "{root}/db.sqlite"')
                      .replace('weekday_times = [', '# original weekdays\n# weekday_times = [')
                      .replace('weekend_times = [', '# original weekends\n# weekend_times = [')
                      + f'\nweekday_times = ["{hour:02}:00"]\nweekend_times = ["{hour:02}:00"]\n')
    env.update(AUTOLYCUS_ACCESS_TOKEN="test", AUTOLYCUS_FEISHU_WEBHOOK="test",
               AUTOLYCUS_BASE_URL="https://backend.invalid", TZ="UTC")
    command = [sys.executable, "-m", "autolycus.cron", "--config", str(config)]
    service = subprocess.Popen(command, env=env)
    state = root / "heartbeat.json"
    try:
        for _ in range(100):
            if healthy(state):
                break
            assert service.poll() is None
            time.sleep(.1)
        assert healthy(state)
        duplicate = subprocess.run(command, env=env, timeout=10)
        assert duplicate.returncode != 0
        assert service.poll() is None
        assert "Asia/Shanghai" in (root / "crontab").read_text()
    finally:
        service.terminate()
        service.wait(timeout=20)
    assert not healthy(state)
print("Cron binary, startup, non-root jobs, health, locking and shutdown passed.")
