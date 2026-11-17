#!/usr/bin/env bash
set -Eeuo pipefail
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)
cd "$ROOT"
umask 077
command -v docker >/dev/null || { echo 'Docker Engine is required.' >&2; exit 1; }
docker compose version >/dev/null
docker info >/dev/null
mkdir -p .deploy backups
exec 9>.deploy/deploy.lock
flock -n 9 || { echo 'Another deployment operation is running.' >&2; exit 1; }
if [[ ! -f .env || ! -f config.toml ]]; then
    [[ -f .env ]] || cp .env.example .env
    [[ -f config.toml ]] || cp config/deployment.example.toml config.toml
    chmod 600 .env
    chmod 644 config.toml
    echo 'Created local templates. Edit .env and config.toml, then run again.' >&2
    exit 1
fi
chmod 600 .env
# Config contains no secrets; the non-root container must be able to read it.
chmod 644 config.toml
if [[ -f .deploy/active-image ]]; then
    AUTOLYCUS_IMAGE=$(cat .deploy/active-image)
    export AUTOLYCUS_IMAGE
fi
compose() { docker compose --project-directory "$ROOT" -f "$ROOT/compose.yaml" "$@"; }
compose config --quiet
wait_healthy() {
    local cid health
    for ((i=0; i<45; i++)); do
        cid=$(compose ps -q monitor)
        health='missing'
        if [[ -n "$cid" ]]; then health=$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$cid"); fi
        if [[ "$health" == healthy ]]; then return 0; fi
        sleep 2
    done
    echo 'Scheduler health check failed; inspect docker compose logs.' >&2
    return 1
}
check_config() {
    compose run --rm --no-deps -T monitor python -c 'from autolycus.config import load_config; from autolycus.daemon import preflight; preflight(load_config("/etc/autolycus/config.toml")); print("Configuration preflight passed; no messages sent.")'
}
backup() {
    local destination="$ROOT/backups/$(date -u +%Y%m%dT%H%M%SZ)-$RANDOM.sqlite"
    # SQLite online backup, never a raw copy of an open database.
    if ! compose run --rm --no-deps -T monitor python -c 'import os,sys; from pathlib import Path; from autolycus.maintenance import backup_database; backup_database(os.environ["AUTOLYCUS_DATABASE"],"/tmp/snapshot.db"); sys.stdout.buffer.write(Path("/tmp/snapshot.db").read_bytes())' > "$destination"; then
        echo 'Backup failed; deployment aborted. Partial backup retained for inspection.' >&2
        return 1
    fi
    chmod 600 "$destination"
    echo "Database backup: $destination"
}
save_image() { printf '%s\n' "$AUTOLYCUS_IMAGE" > .deploy/active-image.tmp; mv .deploy/active-image.tmp .deploy/active-image; }
