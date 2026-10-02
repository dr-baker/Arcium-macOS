#!/usr/bin/env bash
# Focused cold source/dependency acquisition. Sourced by the actual harness.
# Resources, version metadata, GN defaults, and warm dispatch belong to dev.sh.
case "$_arch" in
    arm64) export HELIUM_DEV_ACQUISITION_TARGET=arm64 ;;
    x86_64) export HELIUM_DEV_ACQUISITION_TARGET=x86_64 ;;
    *) echo "error: unsupported acquisition architecture: $_arch" >&2; return 2 ;;
esac

___helium_info_pull() {
    local _resolved_source_mode
    if [ "$_source_mode" = "full" ]; then
        "$_root_dir/retrieve_and_unpack_resource.sh" -g "$HELIUM_DEV_ACQUISITION_TARGET" || return
        _resolved_source_mode=full
    elif "$_root_dir/retrieve_and_unpack_resource.sh" -d -g "$HELIUM_DEV_ACQUISITION_TARGET"; then
        _resolved_source_mode=lite
    else
        "$_root_dir/retrieve_and_unpack_resource.sh" -g "$HELIUM_DEV_ACQUISITION_TARGET" || return
        _resolved_source_mode=full
    fi

    mkdir -p "$(dirname "$_source_mode_marker")" || return
    printf '%s\n' "$_resolved_source_mode" > "${_source_mode_marker}.tmp.$$" || return
    mv "${_source_mode_marker}.tmp.$$" "$_source_mode_marker" || return
    _source_mode="$_resolved_source_mode"
    export HELIUM_DEV_SOURCE_MODE="$_source_mode"

    mkdir -p "$_out_dir" || return
    cd "$_src_dir" || return
}

___helium_toolchain() {
    "$_root_dir/retrieve_and_unpack_resource.sh" -t
}

___helium_acquire_inner() {
    local _acquisition_entry
    _acquisition_entry="$(___helium_preparation begin acquisition)" || return
    ___helium_preparation invalidate acquisition || return
    ___helium_setup_python || return
    rm -rf "$_src_dir" && mkdir -p "$_download_cache" "$_src_dir" || return

    ___helium_info_pull || return
    if [ "$_source_mode" = "full" ]; then
        echo "preserving full Chromium source and test data"
    else
        ___helium_python "$_main_repo/utils/prune_binaries.py" "$_src_dir" "$_main_repo/pruning.list" || return
    fi
    ___helium_toolchain || return
    local _target_marker="$_build_dir/.arcium/acquisition-target"
    printf '%s\n' "$HELIUM_DEV_ACQUISITION_TARGET" > "${_target_marker}.tmp.$$" || return
    mv "${_target_marker}.tmp.$$" "$_target_marker" || return
    ___helium_preparation finish acquisition "$_acquisition_entry" || return
}
