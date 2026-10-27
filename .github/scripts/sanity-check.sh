#!/bin/bash
set -exo pipefail

sudo mdutil -a -i off || echo "::warning::Spotlight indexing could not be disabled; continuing with validation."

brew install ninja coreutils python@3.14 quilt llvm@20 --overwrite
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
cd "$_src_dir"
timeout 30 ninja -C "$_out_dir" chrome chromedriver
_status_code=$?

# The smoke build may finish successfully before the time limit.
if [ "$_status_code" -ne 0 ] && [ "$_status_code" -ne 124 ]; then
    echo "failed with status code $_status_code" >&2
    exit 1
fi
