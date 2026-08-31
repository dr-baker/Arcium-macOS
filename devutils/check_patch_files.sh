#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -P "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLATFORM_ROOT="$(cd -P "$SCRIPT_DIR/.." && pwd)"

exec env PYTHONDONTWRITEBYTECODE=1 python3 "$PLATFORM_ROOT/devutils/check_patch_files.py" \
    -p "$PLATFORM_ROOT/patches" "$@"
