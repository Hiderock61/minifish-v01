#!/usr/bin/env bash
set -euo pipefail

export MINIFISH_RUN_ROOT="${MINIFISH_RUN_ROOT:-$PWD/.minifish/runs}"
export MINIFISH_PROFILE_PATH="${MINIFISH_PROFILE_PATH:-$PWD/.minifish/profile.json}"

mkdir -p "$MINIFISH_RUN_ROOT" "$(dirname "$MINIFISH_PROFILE_PATH")"

exec uvicorn cloud_api:app --host 0.0.0.0 --port 8000
