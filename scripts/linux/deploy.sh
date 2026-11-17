#!/usr/bin/env bash
set -Eeuo pipefail
source "$(dirname -- "$0")/common.sh"
if [[ -n "$(compose ps -q monitor)" ]]; then echo 'Existing deployment found; use upgrade.sh.' >&2; exit 1; fi
revision=$(git rev-parse --short HEAD 2>/dev/null || printf 'workingtree')
export AUTOLYCUS_IMAGE="autolycus:deploy-$(date -u +%Y%m%d%H%M%S)"
export APP_VERSION="$revision"
compose build monitor
check_config
save_image
compose up -d --no-build monitor
wait_healthy
echo "Deployed $AUTOLYCUS_IMAGE ($APP_VERSION). This confirms scheduler health, not business delivery."
