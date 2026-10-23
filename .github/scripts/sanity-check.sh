#!/bin/bash
set -exo pipefail

sudo mdutil -a -i off

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

set +e
if grep -q 'offset .* lines' setup.log; then
    grep -A20 -B20 'offset .* lines' setup.log >&2
    exit 1
fi

cd "$_src_dir"
timeout 30 ninja -C out/Default chrome chromedriver
_status_code=$?

if [ $_status_code != 124 ]; then
    echo "failed with status code $_status_code" >&2
    exit 1
fi
