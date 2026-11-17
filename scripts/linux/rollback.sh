#!/usr/bin/env bash
set -Eeuo pipefail
source "$(dirname -- "$0")/common.sh"
[[ -f .deploy/previous-image ]] || { echo 'No previous image recorded.' >&2; exit 1; }
previous=$(cat .deploy/previous-image)
docker image inspect "$previous" >/dev/null
compose stop monitor
backup
export AUTOLYCUS_IMAGE="$previous"
save_image
compose up -d --no-build monitor
if ! wait_healthy; then
    compose stop monitor
    echo 'Rollback image cannot read current data/config. Do not overwrite database; follow recovery guide.' >&2
    exit 1
fi
echo 'Previous image restored. Database was not rolled back; inspect delivery state.'
