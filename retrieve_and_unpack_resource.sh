#!/usr/bin/env bash

# Script to retrieve and unpack resources to build Chromium macOS

set -euo pipefail

_root_dir="$(dirname "$(greadlink -f "$0")")"
_build_dir="${HELIUM_DEV_BUILD_ROOT:-$_root_dir/build}"
_download_cache="${HELIUM_DEV_DOWNLOAD_CACHE:-$_build_dir/download_cache}"
_src_dir="$_build_dir/src"
_main_repo="$_root_dir/helium-chromium"

source "$_root_dir/devutils/setup_python.sh"
___helium_setup_python

# Clone to get the Chromium Source
clone=true
retrieve_generic=false
retrieve_toolchain=false

while getopts 'dgt' OPTION; do
  case "$OPTION" in
    d)
        clone=false
        ;;
    g)
        retrieve_generic=true
        ;;
    t)
        retrieve_toolchain=true
        ;;
    ?)
        echo "Usage: $0 [-d] [-g] [-p]"
        echo "  -d: Use download instead of git clone to get Chromium Source"
        echo "  -g: Retrieve and unpack Chromium Source and general resources"
        echo "  -t: Retrieve and unpack Chromium toolchain"
        exit 1
        ;;
    esac
done

shift "$(($OPTIND -1))"

_target_cpu=${1:-arm64}

if $retrieve_generic; then
    downloads=("$_root_dir/downloads.ini" "$_main_repo/deps.ini")
    if $clone; then
        if [[ $_target_cpu == "arm64" ]]; then
            # For arm64 (Apple Silicon)
            ___helium_python "$_main_repo/utils/clone.py" -p mac-arm -o "$_src_dir"
        else
            # For amd64 (Intel)
            ___helium_python "$_main_repo/utils/clone.py" -p mac -o "$_src_dir"
        fi
    else
        case "$(uname -m)" in
            arm64) host_arch=arm64 ;;
            x86_64) host_arch=x64 ;;
            *) echo "Unsupported macOS host architecture" >&2; exit 1 ;;
        esac
        downloads=("$_main_repo/downloads.ini" "$_root_dir/downloads.$host_arch.ini" "${downloads[@]}")
    fi

    ___helium_python "$_main_repo/utils/downloads.py" retrieve -i "${downloads[@]}" -c "$_download_cache"
    ___helium_python "$_main_repo/utils/downloads.py" unpack -i "${downloads[@]}" -c "$_download_cache" "$_src_dir"
fi

if $retrieve_toolchain; then
    # Prepared host overlays and gclient hooks supply the pinned toolchain.
    test -x "$_src_dir/buildtools/mac/gn"
    test -x "$_src_dir/third_party/llvm-build/Release+Asserts/bin/clang"
fi
