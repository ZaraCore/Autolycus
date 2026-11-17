#!/usr/bin/env bash
set -Eeuo pipefail
source "$(dirname -- "$0")/common.sh"
case "${1:-status}" in
    pause) compose stop monitor ;;
    resume) compose up -d --no-build monitor ;;
    status) compose ps; compose exec -T monitor python -m autolycus --config /etc/autolycus/config.toml --status ;;
    preview) compose run --rm --no-deps -T monitor python -m autolycus --config /etc/autolycus/config.toml ;;
    logs) compose logs --tail 100 monitor ;;
    backup) backup ;;
    *) echo 'Usage: manage.sh pause|resume|status|preview|logs|backup' >&2; exit 1 ;;
esac
