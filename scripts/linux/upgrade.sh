#!/usr/bin/env bash
set -Eeuo pipefail
main() {
    source "$(dirname -- "$0")/common.sh"
    local ref=${1:?Usage: bash scripts/linux/upgrade.sh TAG_OR_BRANCH}
    [[ "$ref" =~ ^[A-Za-z0-9][A-Za-z0-9._/-]*$ ]] || { echo 'Invalid Git ref.' >&2; exit 1; }
    git rev-parse --is-inside-work-tree >/dev/null
    local cid old_image commit release new_image
    cid=$(compose ps -q monitor)
    [[ -n "$cid" ]] || { echo 'No running deployment; use deploy.sh.' >&2; exit 1; }
    old_image=$(docker inspect --format '{{.Image}}' "$cid")
    git fetch origin "$ref"
    commit=$(git rev-parse FETCH_HEAD)
    mkdir -p .releases
    release=$(mktemp -d "$ROOT/.releases/source.XXXXXX")
    git archive "$commit" | tar -x -C "$release"
    new_image="autolycus:git-$commit"
    # Build before stopping the old service; no dirty-tree checkout or config replacement.
    docker build --build-arg "APP_VERSION=$commit" -t "$new_image" -f "$release/deploy/docker/Dockerfile" "$release"
    local previous=${AUTOLYCUS_IMAGE:-autolycus:local}
    export AUTOLYCUS_IMAGE="$new_image"
    check_config
    export AUTOLYCUS_IMAGE="$previous"
    compose stop monitor
    if ! backup; then compose start monitor; exit 1; fi
    printf '%s\n' "$old_image" > .deploy/previous-image
    export AUTOLYCUS_IMAGE="$new_image"
    save_image
    if ! compose up -d --no-build monitor || ! wait_healthy; then
        compose stop monitor || true
        echo 'Upgrade failed. Container stopped; backup and previous image retained. Run rollback.sh.' >&2
        exit 1
    fi
    printf '%s\n' "$commit" > .deploy/source-revision
    echo "Upgraded runtime image to $commit. Local configuration and data retained."
}
main "$@"
