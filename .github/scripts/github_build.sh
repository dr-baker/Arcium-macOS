#!/bin/bash -eux

# Simple partitioned (2 of 3) build script for building Helium macOS binaries on GitHub Actions
# Resuming build script for macOS

_target_cpu="${1:-x86_64}"

_root_dir="$(dirname "$(greadlink -f "$0")")"
_src_dir="$_root_dir/build/src"
export PYTHONPATH="$_root_dir/devutils${PYTHONPATH:+:$PYTHONPATH}"
case "$_target_cpu" in arm64|x86_64) ;; *) echo 'Unsupported CI architecture' >&2; exit 2 ;; esac
if [[ -f "$_root_dir/epoch_job_start.txt" ]]; then
  epoch_job_start=$(cat "$_root_dir/epoch_job_start.txt")
  # GitHub's hard time limit is 6 h per job, we want to spare 1 h for steps before and after the build,
  # To get the remaining time for building we subtract 360*60s - 60*60s - (epoch_now - epoch_job_start)
  _remaining_time=$(( 360*60 - 60*60 - $(date +%s) + epoch_job_start ))
fi

cd "$_src_dir"

echo $(date +%s) | tee -a "$_root_dir/build_times_$_target_cpu.log"
echo "status=running" >> $GITHUB_OUTPUT
echo "evidence_key=$(python3 -c 'import uuid; print(uuid.uuid4().hex)')" >> "$GITHUB_OUTPUT"
# A marker from a previous attempt must never certify this attempt as complete.
rm -f "$_root_dir/build_finished_$_target_cpu.log"

# An exhausted job should preserve its outputs for the next partition without
# starting a compiler or passing a negative duration to timeout.
if (( ${_remaining_time:-19680} <= 0 )); then
    exit 0
fi

if ! env | grep -q SCCACHE; then
    export SCCACHE_GHA_ENABLED=on
    export SCCACHE_GHA_VERSION="$_target_cpu"
fi

export SCCACHE_WEBDAV_KEY_PREFIX="$_target_cpu"

set +e

timeout -k 7m -s SIGTERM ${_remaining_time:-19680}s \
    python3 -m he.release --worktree "$_root_dir" ci --arch "$_target_cpu" chrome chromedriver

_error_code="${?}"
if [[ "$_error_code" -eq 124 ]]; then
    exit 0
fi

if [[ "$_error_code" -ne 0 ]]; then
    exit "$_error_code"
fi

set -e

echo $(date +%s) | tee "$_root_dir/build_finished_$_target_cpu.log"
echo "status=finished" >> $GITHUB_OUTPUT
