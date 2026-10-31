#!/bin/bash
set -exo pipefail

sudo mdutil -a -i off || echo "::warning::Spotlight indexing could not be disabled; continuing with validation."

brew install ninja coreutils python@3.14 quilt zstd llvm@20 --overwrite
brew unlink python || true
brew link python@3.14 llvm@20 --force

pip3.14 install httplib2==0.22.0 requests Pillow --break

source dev.sh

# CI runners have less free disk than a full local build needs; the setup
# here stops after a short build, so skip the 100 GiB check.
he setup --force | tee setup.log

if [ "$1" = "sub" ]; then
    he sub

    cd "$_src_dir"
    grep -q Arcium components/omnibox_strings.grdp
    exit 0
fi

# Setup enforces zero fuzz; matching context may move as earlier patches grow.
set +e

_smoke_since_ns=$(python3 -c 'import time; print(time.time_ns())')
# The allowance includes the guarded plan. A timeout counts only if the build
# actually launched and finalized its evidence; planning alone is insufficient.
# Time the lock owner so cancellation drains before evidence is checked. A shell
# wrapper can exit on TERM while its supervised build is still shutting down.
PYTHONPATH="$_root_dir/devutils" timeout -k 7m -s SIGTERM 120s \
    python3 -m he --worktree "$_root_dir" --build-dir "$HELIUM_DEV_BUILD_ROOT" \
    --build-mode "$_he_build_mode" lock --label build -- bash -c \
    'source "$1/dev.sh"; he agent build --execution local --approved chrome chromedriver' _ "$_root_dir"
_status_code=$?

# The smoke build may finish successfully before the time limit.
if [ "$_status_code" -ne 0 ] && [ "$_status_code" -ne 124 ]; then
    echo "failed with status code $_status_code" >&2
    exit 1
fi
PYTHONPATH="$_root_dir/devutils" python3 -m he.ci --state "$HELIUM_DEV_BUILD_ROOT/.arcium" \
    --since-ns "$_smoke_since_ns" --status "$_status_code"
