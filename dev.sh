#!/usr/bin/env bash

# This file is normally sourced.  $0 points at the caller in both Bash and
# zsh, so resolve the source file first.  HELIUM_DEV_WORKTREE lets a landed
# harness safely operate on another worktree without copying tooling into its
# possibly dirty checkout.
if [ -n "${ZSH_VERSION:-}" ]; then
    _helium_dev_script_path="${(%):-%x}"
elif [ -n "${BASH_SOURCE[0]:-}" ]; then
    _helium_dev_script_path="${BASH_SOURCE[0]}"
else
    _helium_dev_script_path="$0"
fi
_helium_harness_root="$(cd -P "$(dirname "$_helium_dev_script_path")" && pwd)"
_root_dir="${HELIUM_DEV_WORKTREE:-$_helium_harness_root}"
_root_dir="$(cd -P "$_root_dir" && pwd)"

_git_common_dir="$(git -C "$_root_dir" rev-parse --path-format=absolute --git-common-dir 2>/dev/null)"
_canonical_root="$(dirname "$_git_common_dir")"
# A previous source call may have left auto-selected values in the shell.  They
# must not turn into explicit approval on the next source call.
if [ "${HELIUM_DEV_AUTO_SELECTED:-0}" = 1 ] && \
   [ "${HELIUM_DEV_LANE:-}" = "${HELIUM_DEV_AUTO_LANE:-}" ] && \
   [ "${HELIUM_DEV_BUILD_ROOT:-}" = "${HELIUM_DEV_AUTO_BUILD_ROOT:-}" ]; then
    unset HELIUM_DEV_LANE HELIUM_DEV_BUILD_ROOT
fi
_lane_was_explicit=0
if [ -n "${HELIUM_DEV_BUILD_ROOT:-}" ] && [ -z "${HELIUM_DEV_LANE:-}" ]; then
    echo "error: HELIUM_DEV_BUILD_ROOT requires an explicit HELIUM_DEV_LANE" >&2
    return 2 2>/dev/null || exit 2
fi
if [ -n "${HELIUM_DEV_LANE:-}" ] || [ -n "${HELIUM_DEV_BUILD_ROOT:-}" ]; then
    _lane_was_explicit=1
fi
_local_build_dir="$_canonical_root/build"
_heavy_build_dir="${HELIUM_DEV_HEAVY_ROOT:-/Volumes/T9/ArciumBuild/build}"
if [ -n "${HELIUM_DEV_LANE:-}" ]; then
    _dev_lane="$HELIUM_DEV_LANE"
elif [ -f "$_heavy_build_dir/src/out/Default/build.ninja" ]; then
    _dev_lane="heavy"
elif [ -f "$_local_build_dir/src/out/Default/build.ninja" ]; then
    _dev_lane="local"
else
    _dev_lane="local"
fi
case "$_dev_lane" in
    local) _default_build_dir="$_local_build_dir";;
    heavy) _default_build_dir="$_heavy_build_dir";;
    worktree) _default_build_dir="$_root_dir/build";;
    *)
        echo "error: HELIUM_DEV_LANE must be local, heavy, or worktree" >&2
        return 2 2>/dev/null || exit 2
        ;;
esac
_build_dir="${HELIUM_DEV_BUILD_ROOT:-$_default_build_dir}"
_source_mode_marker="$_build_dir/.arcium/source-mode"
_source_mode="${HELIUM_DEV_SOURCE_MODE:-}"
if [ -z "$_source_mode" ] && [ -f "$_source_mode_marker" ]; then
    _source_mode="$(head -1 "$_source_mode_marker")"
fi
_source_mode="${_source_mode:-lite}"
case "$_source_mode" in
    lite|full) ;;
    *)
        echo "error: HELIUM_DEV_SOURCE_MODE must be lite or full" >&2
        return 2 2>/dev/null || exit 2
        ;;
esac
_heavy_volume_uuid="${HELIUM_DEV_HEAVY_VOLUME_UUID:-75279EDB-CF1D-4EBF-8C7C-FD7249DCBCAF}"
export HELIUM_DEV_LANE="$_dev_lane"
export HELIUM_DEV_BUILD_ROOT="$_build_dir"
export HELIUM_DEV_SOURCE_MODE="$_source_mode"
if [ "$_lane_was_explicit" = 0 ]; then
    export HELIUM_DEV_AUTO_SELECTED=1 HELIUM_DEV_AUTO_LANE="$_dev_lane" HELIUM_DEV_AUTO_BUILD_ROOT="$_build_dir"
else
    unset HELIUM_DEV_AUTO_SELECTED HELIUM_DEV_AUTO_LANE HELIUM_DEV_AUTO_BUILD_ROOT
fi
_patches_dir="$_build_dir/.arcium/patches"
export HELIUM_DEV_GENERATED_PATCH_ROOT="$_patches_dir"

# Keep the old environment contract while making its paths unambiguously
# relative to the selected worktree rather than the interactive shell.
_arch="$(/usr/bin/uname -m)"
_download_cache="${HELIUM_DEV_DOWNLOAD_CACHE:-$_build_dir/download_cache}"
_src_dir="$_build_dir/src"
_out_dir="$_src_dir/out/Default"
_main_repo="$_root_dir/helium-chromium"
_subs_cache="$_build_dir/subs.tar.gz"
_namesubs_cache="$_build_dir/namesubs.tar"
_depot_tools_dir="$_src_dir/third_party/depot_tools"
_siso_dir="$_src_dir/third_party/siso/cipd"
_siso_path="$_siso_dir/siso"

source "$_root_dir/devutils/setup_python.sh"

alias quilt='quilt --quiltrc -'
export QUILT_PATCHES="$_patches_dir"
export QUILT_SERIES="series.merged"
export QUILT_PUSH_ARGS="--color=auto"
export QUILT_DIFF_OPTS="--show-c-function"
export QUILT_PATCH_OPTS="--unified --reject-format=unified"
export QUILT_DIFF_ARGS="-p ab --no-timestamps --no-index --color=auto"
export QUILT_REFRESH_ARGS="-p ab --no-timestamps --no-index"
export QUILT_COLORS="diff_hdr=1;32:diff_add=1;34:diff_rem=1;31:diff_hunk=1;33:diff_ctx=35:diff_cctx=33"
export QUILT_SERIES_ARGS="--color=auto"
export QUILT_PATCHES_ARGS="--color=auto"

___helium_setup_siso() {
    if [ ! -x "$_siso_path" ]; then
        local siso_arch="mac-arm64"
        if [[ $_arch == "x86_64" ]]; then
            siso_arch="mac-amd64"
        fi

        local siso_package="build/siso/$siso_arch"

        local siso_version=$(sed -n "s/.*'siso_version': '\([^']*\)'.*/\1/p" "$_src_dir/DEPS" | head -1)
        if [ -z "$siso_version" ]; then
            echo "error: couldn't find siso_version in DEPS" >&2
            return 1
        fi

        mkdir -p "$_siso_dir" || return
        printf '%s\n' "$siso_package $siso_version" |
            "$_depot_tools_dir/cipd" ensure --root "$_siso_dir" --ensure-file - || return
    fi

    local siso_env="$_src_dir/build/config/siso/.sisoenv"
    if [ ! -f "$siso_env" ]; then
        # Full-source acquisition intentionally skips gclient hooks. Recreate
        # the pinned Chromium checkout's normal developer Siso configuration.
        ___helium_python "$_src_dir/build/config/siso/configure_siso.py" \
            --rbe_instance projects/rbe-chrome-untrusted/instances/default_instance || return
    fi
}

___helium_setup_gn() {
    local OUT_FILE="$_out_dir/args.gn"
    cat "$_main_repo/flags.gn" "$_root_dir/flags.macos.gn" > "$OUT_FILE" || return

    if command -v sccache 2>&1 >/dev/null; then
        echo 'cc_wrapper="sccache"' >> "$OUT_FILE" || return
    elif command -v ccache 2>&1 >/dev/null; then
        echo 'cc_wrapper="env CCACHE_COMPILERCHECK=content CCACHE_SLOPPINESS=time_macros ccache"' >> "$OUT_FILE" || return
    else
        echo 'warn: sccache or ccache is not available' >&2
    fi

    local TARGET_CPU="arm64"
    if [[ $_arch == "x86_64" ]]; then
        TARGET_CPU="x64"
    fi

    echo 'target_cpu = "'"$TARGET_CPU"'"' >> "$OUT_FILE" || return
    echo 'devtools_skip_typecheck = false' >> "$OUT_FILE" || return
    echo 'use_siso = true' >> "$OUT_FILE" || return

    sed -i '' s/is_official_build/is_component_build/ "$OUT_FILE" || return
}

___helium_info_pull() {
    local _resolved_source_mode
    if [ "$_source_mode" = "full" ]; then
        "$_root_dir/retrieve_and_unpack_resource.sh" -g || return
        _resolved_source_mode=full
    elif "$_root_dir/retrieve_and_unpack_resource.sh" -d -g; then
        _resolved_source_mode=lite
    else
        "$_root_dir/retrieve_and_unpack_resource.sh" -g || return
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

___helium_configure_inner() {
    ___helium_setup_python || return

    cd "$_src_dir" || return
    ___helium_setup_siso || return
    "$_root_dir/devutils/setup_dawn_go.sh" "$_src_dir" "$_depot_tools_dir" "$_arch" || return
    ___helium_python ./tools/gn/bootstrap/bootstrap.py -o "$_out_dir/gn" --skip-generate-buildfiles || return
    "$_out_dir/gn" gen "$_out_dir" --fail-on-unused-args --export-compile-commands || return
}

___helium_configure() {
    ___helium_lane_preflight 15 || return
    ___helium_lane_transaction configure
}

___helium_toolchain() {
    "$_root_dir/retrieve_and_unpack_resource.sh" -t
}

___helium_resources_inner() {
    ___helium_setup_python || return

    ___helium_python "$_main_repo/utils/generate_resources.py" "$_main_repo/resources/generate_resources.txt" "$_main_repo/resources" || return
    ___helium_python "$_main_repo/utils/replace_resources.py" "$_root_dir/resources/platform_resources.txt" "$_root_dir/resources" "$_src_dir" || return
    ___helium_python "$_main_repo/utils/replace_resources.py" "$_main_repo/resources/helium_resources.txt" "$_main_repo/resources" "$_src_dir" || return
}

___helium_resources() {
    ___helium_lane_preflight 15 || return
    ___helium_lane_transaction resources
}

___helium_version() {
    if [ ! -f "$_src_dir/chrome/VERSION" ]; then
        echo "error: Chromium source is missing chrome/VERSION" >&2
        return 1
    fi
    if grep -q '^HELIUM_MAJOR=' "$_src_dir/chrome/VERSION"; then
        return 0
    fi

    ___helium_setup_python || return
    ___helium_python "$_main_repo/utils/helium_version.py" \
        --tree "$_main_repo" \
        --platform-tree "$_root_dir" \
        --chromium-tree "$_src_dir" || return
}

___helium_setup_presetup_inner() {
    if [ -d "$_src_dir/out" ]; then
        ___helium_lane_preflight 15 || return
    else
        ___helium_lane_preflight 80 || return
    fi
    ___helium_setup_python || return

    if [ -d "$_src_dir/out" ]; then
        echo "$_src_dir/out already exists" >&2
        ___helium_version || return
        return
    fi

    rm -rf "$_src_dir" && mkdir -p "$_download_cache" "$_src_dir" || return

    ___helium_info_pull || return
    if [ "$_source_mode" = "full" ]; then
        echo "preserving full Chromium source and test data"
    else
        ___helium_python "$_main_repo/utils/prune_binaries.py" "$_src_dir" "$_main_repo/pruning.list" || return
    fi
    ___helium_toolchain || return
    ___helium_resources_inner || return
    ___helium_setup_gn || return

    ___helium_version || return
}

___helium_setup_presetup() {
    ___helium_lane_transaction presetup
}

___helium_setup_inner() {
    ___helium_setup_presetup_inner || return

    ___helium_prepare_patches_inner || return

    ___helium_quilt_push_inner || return

    # A complete applied ledger is not replay proof. Rebuild the stack once
    # from its clean preimages before setup is allowed to configure or build.
    ___helium_replay || return

    ___helium_configure_inner || return
}

___helium_setup() {
    ___helium_lane_transaction setup
}

___helium_reset_inner() {
    if [ "$1" != "--warm-output" ] || [ "$2" != "--approved" ] || [ -n "$3" ]; then
        echo "reset preserves the warm build by default." >&2
        echo "use 'he reset --warm-output --approved' to remove it deliberately." >&2
        return 2
    fi
    rm "$_subs_cache" || true
    rm "$_namesubs_cache" || true
    mv "$_src_dir" "${_src_dir}x" || return
    rm -rf "${_src_dir}x" || return
}

___helium_reset() {
    ___helium_lane_transaction reset "$@"
}

___helium_name_substitution_inner() {
    if [ "$1" = "nameunsub" ]; then
        ___helium_python "$_main_repo/utils/name_substitution.py" --unsub \
            -t "$_src_dir" --backup-path "$_namesubs_cache" || return
    elif [ "$1" = "namesub" ]; then
        if [ -f "$_namesubs_cache" ]; then
            echo "$_namesubs_cache exists, are you sure you want to do this?" >&2
            echo "if yes, then delete the $_namesubs_cache file" >&2
            return 2
        fi

        ___helium_python "$_main_repo/utils/name_substitution.py" --sub \
            -t "$_src_dir" --backup-path "$_namesubs_cache" || return
    else
        echo "unknown action: $1" >&2
        return 2
    fi
}

___helium_name_substitution() {
    ___helium_lane_transaction name-substitution "$@"
}

___helium_apply_translations_inner() {
    ___helium_python "$_main_repo/utils/i18n_apply.py" -t "$_src_dir"
}

___helium_apply_translations() {
    ___helium_lane_transaction translate
}

___helium_generate_translations_inner() {
    ___helium_python "$_main_repo/devutils/i18n.py" generate
}

___helium_generate_translations() {
    ___helium_lane_transaction transgen
}

___helium_substitution_inner() {
    if [ "$1" = "unsub" ]; then
        ___helium_python "$_main_repo/utils/domain_substitution.py" revert \
            -c "$_subs_cache" "$_src_dir" || return

        ___helium_name_substitution_inner nameunsub || return
    elif [ "$1" = "sub" ]; then
        if [ -f "$_subs_cache" ]; then
            echo "$_subs_cache exists, are you sure you want to do this?" >&2
            echo "if yes, then delete the $_subs_cache file" >&2
            return 2
        fi

        ___helium_name_substitution_inner namesub || return

        ___helium_python "$_main_repo/utils/domain_substitution.py" apply \
            -r "$_main_repo/domain_regex.list" \
            -f "$_main_repo/domain_substitution.list" \
            -c "$_subs_cache" \
            "$_src_dir" || return
    else
        echo "unknown action: $1" >&2
        return 2
    fi
}

___helium_substitution() {
    ___helium_lane_transaction substitution "$@"
}

___helium_build() {
    echo "he build is disabled because it would start a broad Chromium build." >&2
    echo "use he build-plan TARGET..., he compile TARGET..., he relink, or he build-full --approved" >&2
    return 2
}

___helium_harness() {
    ___helium_python "$_helium_harness_root/devutils/helium_dev.py" \
        --root "$_root_dir" --build-root "$_build_dir" "$@"
}

___helium_lane_transaction() {
    local _action="$1"
    shift
    local _uuid_args=()
    if [ "$_dev_lane" = "heavy" ]; then
        _uuid_args=(--expected-volume-uuid "$_heavy_volume_uuid")
    fi
    ___helium_python "$_helium_harness_root/devutils/lane_transaction.py" \
        --worktree "$_root_dir" \
        --build-root "$_build_dir" \
        --lane "$_dev_lane" \
        --script "$_helium_harness_root/dev.sh" \
        "${_uuid_args[@]}" \
        "$_action" -- "$@"
}

___helium_lane_preflight() {
    local _minimum_free_gib="${1:-15}"
    if [ -f "$_src_dir/.pc/.quilt_patches" ]; then
        local _legacy_patches
        _legacy_patches="$(sed -n '1p' "$_src_dir/.pc/.quilt_patches")"
        if [ -n "$_legacy_patches" ] && [ "$_legacy_patches" != "$_patches_dir" ]; then
            if [ -f "$_src_dir/.pc/applied-patches" ] && \
                    grep -Eq '^[[:space:]]*[^#[:space:]]' "$_src_dir/.pc/applied-patches"; then
                echo "error: Quilt source uses legacy patch root $_legacy_patches; fully pop it with the legacy QUILT_PATCHES, then rerun setup to migrate into $_patches_dir" >&2
                return 1
            fi
        fi
    fi
    local _uuid_args=()
    if [ "$_dev_lane" = "heavy" ]; then
        _uuid_args=(--expected-volume-uuid "$_heavy_volume_uuid")
    fi
    ___helium_python "$_helium_harness_root/devutils/build_lane_cli.py" \
        --name "$_dev_lane" \
        --root "$_build_dir" \
        --minimum-free-gib "$_minimum_free_gib" \
        "${_uuid_args[@]}"
}

___helium_prepare_lane_temp() {
    if [ "$_dev_lane" != "heavy" ]; then
        return
    fi
    local _lane_temp="$_build_dir/.arcium/tmp"
    mkdir -p "$_lane_temp" || return
    export TMPDIR="$_lane_temp"
}

___helium_lane() {
    local _json_args=()
    if [ "$1" = "--json" ] && [ -z "$2" ]; then
        _json_args=(--json)
    elif [ -n "$1" ]; then
        echo "he lane accepts only --json" >&2
        return 2
    fi
    local _uuid_args=()
    if [ "$_dev_lane" = "heavy" ]; then
        _uuid_args=(--expected-volume-uuid "$_heavy_volume_uuid")
    fi
    ___helium_python "$_helium_harness_root/devutils/build_lane_cli.py" \
        --name "$_dev_lane" \
        --root "$_build_dir" \
        --minimum-free-gib 0 \
        "${_uuid_args[@]}" \
        "${_json_args[@]}"
}

___helium_context() {
    local _uuid_args=()
    if [ "$_dev_lane" = "heavy" ]; then
        _uuid_args=(--expected-volume-uuid "$_heavy_volume_uuid")
    fi
    ___helium_python "$_helium_harness_root/devutils/development_context.py" \
        --worktree "$_root_dir" \
        --build-root "$_build_dir" \
        --lane "$_dev_lane" \
        "${_uuid_args[@]}" \
        "$@"
}

___helium_run() {
    ___helium_lane_preflight 0 || return
    ___helium_harness run "$@"
}

___helium_dev_bundle() {
    ___helium_lane_preflight 5 || return
    ___helium_harness dev-bundle "$@"
}

___helium_require_replay_proof() {
    ___helium_python "$_helium_harness_root/devutils/replay_contract.py" check \
        --worktree "$_root_dir" --source "$_src_dir"
}

___helium_check_source() {
    ___helium_python "$_helium_harness_root/devutils/check_source.py" \
        --source "$_src_dir"
}

___helium_replay() {
    ___helium_lane_preflight 15 || return
    ___helium_python "$_helium_harness_root/devutils/patch_workspace.py" \
        --worktree "$_root_dir" --build-root "$_build_dir" validate || return
    ___helium_harness replay
}

___helium_status() {
    ___helium_lane_preflight 0 || return
    ___helium_harness status "$@"
}

___helium_activate() {
    ___helium_lane_preflight 0 || return
    ___helium_harness activate "$@"
}

___helium_stop() {
    ___helium_lane_preflight 0 || return
    ___helium_harness stop "$@"
}

___helium_restart() {
    ___helium_lane_preflight 0 || return
    ___helium_harness restart "$@"
}

___helium_build_plan() {
    ___helium_lane_preflight 5 || return
    ___helium_prepare_lane_temp || return
    ___helium_harness build-plan "$@"
}

___helium_compile() {
    ___helium_lane_preflight 15 || return
    ___helium_prepare_lane_temp || return
    ___helium_harness compile "$@"
}

___helium_relink() {
    ___helium_lane_preflight 15 || return
    ___helium_prepare_lane_temp || return
    ___helium_harness relink "$@"
}

___helium_build_full() {
    local _allow_internal=0
    local _build_args=()
    local _argument
    for _argument in "$@"; do
        if [ "$_argument" = "--allow-internal" ]; then
            _allow_internal=1
        else
            _build_args+=("$_argument")
        fi
    done
    if [ "$_dev_lane" = "local" ] && [ "$_allow_internal" != 1 ]; then
        echo "build-full requires explicit approval for internal storage." >&2
        echo "connect T9 or pass --allow-internal after checking free space." >&2
        return 2
    fi
    ___helium_lane_preflight 15 || return
    ___helium_prepare_lane_temp || return
    ___helium_harness build-full "${_build_args[@]}"
}

___helium_check() {
    ___helium_python "$_root_dir/devutils/check_patch_files.py" \
        --patches "$_main_repo/patches" || return
    ___helium_python "$_root_dir/devutils/check_patch_files.py" \
        --patches "$_root_dir/patches" || return

    if [ ! -d "$_src_dir" ] || [ ! -f "$_patches_dir/series.merged" ]; then
        echo "check: authoritative patch catalogs passed; no lane replay is present"
        return 0
    fi

    ___helium_python "$_helium_harness_root/devutils/patch_workspace.py" \
        --worktree "$_root_dir" --build-root "$_build_dir" validate || return

    ___helium_python "$_helium_harness_root/devutils/quilt_state_cli.py" \
        --source "$_src_dir" \
        --patches "$_patches_dir" \
        --series series.merged \
        --complete || return
    if find "$_src_dir" -name '*.rej' -print -quit | grep -q .; then
        echo "check: patch rejects remain in the development source" >&2
        return 1
    fi
    ___helium_check_source || return
    echo "check: active patch stack passed"
}

___helium_bootstrap_inner() {
    local _allow_internal=0
    local _bootstrap_args=()
    local _argument
    for _argument in "$@"; do
        if [ "$_argument" = "--allow-internal" ]; then
            _allow_internal=1
        elif [ "$_argument" = "--full-source" ]; then
            _source_mode=full
            export HELIUM_DEV_SOURCE_MODE=full
        else
            _bootstrap_args+=("$_argument")
        fi
    done
    if [ "${_bootstrap_args[1]:-}" != "--approved" ] || \
            [ -n "${_bootstrap_args[2]:-}" ]; then
        echo "bootstrap performs the rare cold browser build." >&2
        echo "use 'he bootstrap --approved' after reviewing the cost." >&2
        return 2
    fi
    if [ -x "$_out_dir/Helium.app/Contents/MacOS/Helium" ]; then
        echo "bootstrap: warm output already exists; use 'he dev'" >&2
        return 2
    fi

    ___helium_lane_preflight 80 || return

    ___helium_setup_inner || return
    echo "bootstrap: starting the approved cold Arcium browser build" >&2
    local _internal_args=()
    if [ "$_allow_internal" = 1 ]; then
        _internal_args=(--allow-internal)
    fi
    ___helium_build_full --approved "${_internal_args[@]}" \
        --edge-budget 100000 || return
    ___helium_dev_bundle || return
}

___helium_bootstrap() {
    local _allow_internal=0
    local _argument
    for _argument in "$@"; do
        if [ "$_argument" = "--allow-internal" ]; then
            _allow_internal=1
        elif [ "$_argument" = "--full-source" ]; then
            _source_mode=full
            export HELIUM_DEV_SOURCE_MODE=full
        fi
    done
    if [ "$_dev_lane" = "local" ] && [ "$_allow_internal" != 1 ]; then
        echo "bootstrap requires explicit approval for internal storage." >&2
        echo "select the heavy lane, or pass --allow-internal after checking free space." >&2
        return 2
    fi
    ___helium_lane_transaction bootstrap "$@"
}

___helium_dev_inner() {
    local _profile_args=()
    local _arguments=("$@")
    local _index=1
    while [ "$_index" -le "${#_arguments[@]}" ]; do
        local _argument="${_arguments[$_index]}"
        if [ "$_argument" = "--isolated" ] || [ "$_argument" = "--fresh" ]; then
            _profile_args+=("$_argument")
            _index=$((_index + 1))
            if [ "$_index" -le "${#_arguments[@]}" ]; then
                _profile_args+=("${_arguments[$_index]}")
            fi
        elif [[ "$_argument" = --isolated=* ]] || [[ "$_argument" = --fresh=* ]]; then
            _profile_args+=("$_argument")
        fi
        _index=$((_index + 1))
    done
    ___helium_check || return
    ___helium_require_replay_proof || return
    ___helium_configure_inner || return
    ___helium_relink --resources "${_profile_args[@]}" || return
    ___helium_dev_bundle "$@" || return
    ___helium_run "$@"
}

___helium_dev() {
    ___helium_lane_transaction dev "$@"
}

___helium_arcium_inner() {
    if [ -n "$1" ]; then
        echo "he arcium takes no options" >&2
        return 2
    fi
    ___helium_python "$_helium_harness_root/devutils/arcium_app.py" \
        --root "$_root_dir" --build-root "$_build_dir" preflight || return
    ___helium_check || return
    ___helium_configure_inner || return
    ___helium_relink --resources || return
    ___helium_python "$_helium_harness_root/devutils/arcium_app.py" \
        --root "$_root_dir" --build-root "$_build_dir" update || return
}

___helium_arcium() {
    ___helium_lane_transaction arcium "$@"
}

___helium_pull_inner() {
    if [ -f "$_subs_cache" ]; then
        echo "source files are substituted, please run 'he unsub' first" >&2
        return 1
    fi

    ___helium_quilt_pop_inner || return

    for dir in "$_root_dir" "$_main_repo"; do
        git -C "$dir" fetch || return
        git -C "$dir" rebase --autostash origin/main || return
    done

    ___helium_prepare_patches_inner || return
    ___helium_quilt_push_inner || return
}

___helium_pull() {
    ___helium_lane_transaction pull
}

___helium_prepare_patches_inner() {
    ___helium_python "$_helium_harness_root/devutils/patch_workspace.py" \
        --worktree "$_root_dir" \
        --build-root "$_build_dir" \
        --source "$_src_dir" \
        prepare
}

___helium_prepare_patches() {
    ___helium_lane_preflight 15 || return
    ___helium_lane_transaction prepare-patches
}

___helium_sync_patches_inner() {
    ___helium_prepare_patches_inner
}

___helium_sync_patches() {
    ___helium_lane_preflight 15 || return
    ___helium_lane_transaction sync-patches
}

___helium_patches_unmerge_inner() {
    echo "unmerge is retired; generated patch catalogs are lane-local." >&2
    echo "run he pop, then he prepare-patches to regenerate the selected lane." >&2
    return 2
}

___helium_patches_unmerge() {
    ___helium_lane_transaction unmerge
}

___helium_quilt_push_inner() {
    cd "$_src_dir" && QUILT_PATCH_OPTS="$QUILT_PATCH_OPTS --fuzz=0" quilt push -a
}

___helium_quilt_push() {
    ___helium_lane_transaction push
}

___helium_quilt_pop_inner() {
    if [ "$#" -gt 1 ]; then
        echo "usage: he pop [PATCH]" >&2
        return 2
    fi
    if [ "$#" -eq 1 ]; then
        cd "$_src_dir" && quilt pop "$1"
    else
        cd "$_src_dir" && quilt pop -a
    fi
}

___helium_quilt_pop() {
    ___helium_lane_transaction pop "$@"
}

___helium_save_patch_inner() {
    ___helium_python "$_helium_harness_root/devutils/patch_workspace.py" \
        --worktree "$_root_dir" \
        --build-root "$_build_dir" \
        --source "$_src_dir" \
        "$@" \
        save
}

___helium_save_patch() {
    ___helium_lane_preflight 15 || return
    ___helium_lane_transaction save-patch "$@"
}

___helium_validate() {
    if [ "$1" = "config" ]; then
        ___helium_python "$_main_repo/devutils/validate_config.py"
    elif [ "$1" = "patches" ]; then
        local _series_path
        if [ -f "$_patches_dir/series" ] && [ -f "$_patches_dir/series.merged" ]; then
            echo "both patches/series and patches/series.merged exist; resolve the merge state" >&2
            return 1
        elif [ -f "$_patches_dir/series.merged" ]; then
            _series_path="$_patches_dir/series.merged"
        elif [ -f "$_patches_dir/series" ]; then
            _series_path="$_patches_dir/series"
        else
            echo "neither patches/series nor patches/series.merged exists" >&2
            return 1
        fi
        ___helium_python "$_main_repo/devutils/validate_patches.py" \
            -l "$_src_dir" \
            -s "$_series_path"
    elif [ "$1" = "series" ]; then
        ___helium_python "$_root_dir/devutils/check_patch_files.py" \
            --patches "$_main_repo/patches" || return
        ___helium_python "$_root_dir/devutils/check_patch_files.py" \
            --patches "$_root_dir/patches" || return
        if [ -f "$_patches_dir/series.merged" ]; then
            ___helium_python "$_helium_harness_root/devutils/patch_workspace.py" \
                --worktree "$_root_dir" --build-root "$_build_dir" validate
        fi
    else
        echo "unknown validate action. usage: he validate <config|patches|series>" >&2
    fi
}

___helium_format_inner() {
    cd "$_src_dir" || return
    quilt diff | "$_src_dir/third_party/clang-format/script/clang-format-diff.py" \
    -p1 -i -style=file
}

___helium_format() {
    ___helium_lane_transaction format
}

___helium_find_tidy_diff() {
    if [ -n "$_tidy_diff_script" ]; then
        return
    elif command -v clang-tidy-diff >/dev/null 2>&1; then
        _tidy_diff_script=$(command -v clang-tidy-diff)
    elif command -v clang-tidy-diff.py >/dev/null 2>&1; then
        _tidy_diff_script=$(command -v clang-tidy-diff.py)
    else
        _tidy_diff_script=$(find /opt/homebrew/Cellar/llvm -name clang-tidy-diff.py | head -1)
    fi

    if [ -z "$_tidy_diff_script" ]; then
        echo "could not find clang-tidy-diff.py script." >&2
        echo "ensure that you have llvm installed on your system" >&2
        return 1
    fi
}

___helium_strip_compile_commands() {
    _ccmd_path="$_out_dir/compile_commands.json"
    [ "$_ccmd_stripped" = 1 ] && return;
    _ccmd_stripped=1

    echo "normalizing compile_commands.json, this will take a while..."
    cp "$_ccmd_path" "$_ccmd_path.orig";
    gsed -Ei 's/^(\s*"command": ").*?\s(\S+bin\/clang)/\1\2/g' "$_ccmd_path"
}

___helium_tidy_inner() {
    ___helium_find_tidy_diff || return;
    ___helium_strip_compile_commands;
    quilt diff | "$_tidy_diff_script" \
        -regex '.*\.(cc|mm)' \
        -use-color \
        -p1 \
        -path "$_out_dir" \
        -quiet \
        -j$(nproc)
}

___helium_tidy() {
    ___helium_lane_transaction tidy
}

___helium_lint_inner() {
    ___helium_format_inner || return
    ___helium_tidy_inner || return
}

___helium_lint() {
    ___helium_lane_transaction lint
}

__helium_menu() {
    set -e
    case $1 in
        bootstrap) shift; ___helium_bootstrap "$@";;
        arcium) shift; ___helium_arcium "$@";;
        check) shift; ___helium_check "$@";;
        context) shift; ___helium_context "$@";;
        dev) shift; ___helium_dev "$@";;
        lane) shift; ___helium_lane "$@";;
        setup) ___helium_setup;;
        presetup) ___helium_setup_presetup;;
        configure) ___helium_configure;;
        resources) ___helium_resources;;

        sub|unsub) ___helium_substitution "$1";;
        namesub|nameunsub) ___helium_name_substitution "$1";;
        translate) ___helium_apply_translations;;
        transgen) ___helium_generate_translations;;

        merge|prepare-patches) ___helium_prepare_patches;;
        sync-patches) ___helium_sync_patches;;
        unmerge) ___helium_patches_unmerge;;
        push) ___helium_quilt_push;;
        pop) shift; ___helium_quilt_pop "$@";;
        save-patch) shift; ___helium_save_patch "$@";;
        replay) ___helium_replay;;
        pull) ___helium_pull;;

        validate) ___helium_validate "$2";;
        format) ___helium_format;;
        tidy) ___helium_tidy;;
        lint) ___helium_lint;;

        build) ___helium_build;;
        run) shift; ___helium_run "$@";;
        dev-bundle) shift; ___helium_dev_bundle "$@";;
        status) shift; ___helium_status "$@";;
        activate) shift; ___helium_activate "$@";;
        stop) shift; ___helium_stop "$@";;
        restart) shift; ___helium_restart "$@";;
        build-plan) shift; ___helium_build_plan "$@";;
        compile) shift; ___helium_compile "$@";;
        relink) shift; ___helium_relink "$@";;
        build-full) shift; ___helium_build_full "$@";;
        reset) shift; ___helium_reset "$@";;
        *)
            echo "usage: he <command>" >&2
            echo "\tarcium - update, install, and launch the stable personal browser" >&2
            echo "\tbootstrap --approved [--full-source] [--allow-internal] - one-time cold browser build" >&2
            echo "\tcheck - validate the active patch catalog and applied state" >&2
            echo "\tcontext [--json] - show source, lane, proof, bundle, and limitations" >&2
            echo "\treplay - pop and strictly replay the complete patch stack" >&2
            echo "\tdev [profile options] - rebuild and run a labeled Dev app; named profiles seed from installed Helium" >&2
            echo "\tlane - show the selected build lane and storage preflight" >&2
            echo "\tstatus|stop [profile options] - inspect or stop the exact Dev app" >&2
            echo "\thelp --advanced - show low-level maintenance commands" >&2

            if [ "$1" != "help" ] || [ "$2" != "--advanced" ]; then
                return 0
            fi

            echo "\nadvanced:" >&2
            echo "\tsetup - prepares source, patches, and the generated graph without building" >&2
            echo "\tpresetup - downloads sources, sets up GN, and prepares third-party dependencies" >&2
            echo "\tconfigure - generates build configuration and tools" >&2
            echo "\tresources - generates and copies helium resources (such as icons)" >&2

            echo "\n" >&2
            echo "\tsub - apply google domain and name substitutions" >&2
            echo "\tunsub - undo google domain and name substitutions" >&2
            echo "\tnamesub - apply only name substitutions" >&2
            echo "\tnameunsub - undo only name substitutions" >&2
            echo "\ttranslate - apply translations from i18n directory" >&2
            echo "\ttransgen - generate source strings for translation" >&2

            echo "\n" >&2
            echo "\tprepare-patches - rebuilds the selected lane's generated patch catalog" >&2
            echo "\tsync-patches - alias for prepare-patches" >&2
            echo "\tsave-patch - refreshes and exports only the active top patch" >&2
            echo "\tpush - applies all patches" >&2
            echo "\tpop - undoes all patches" >&2
            echo "\treplay - pops and strictly reapplies all patches, then records proof" >&2
            echo "\tpull - undoes all patches, pulls from git, redoes all patches" >&2

            echo "\n" >&2
            echo "\tvalidate config - validates the build configuration" >&2
            echo "\tvalidate patches - validates that patches are applied correctly" >&2
            echo "\tvalidate series - checks the consistency of the series file" >&2
            echo "\tformat - formats the topmost patch according to Chromium coding style" >&2
            echo "\ttidy - runs clang-tidy on the topmost patch" >&2
            echo "\tlint - he format + he tidy" >&2

            echo "\n" >&2
            echo "\trun [--isolated NAME|--fresh NAME] [--seed-from installed|dev|empty] [--preflight] [--json] [browser flags...] - runs or checks the exact labeled Dev bundle" >&2
            echo "\tdev-bundle [profile options] [--json] - clones Helium.app into the selected signed Dev app" >&2
            echo "\tstatus|activate|stop|restart [profile options] [--json] - manage one exact Dev profile" >&2
            echo "\tbuild-plan TARGET... - graph-validate and dry-run explicit targets" >&2
            echo "\tcompile TARGET... - compile explicit focused targets within the edge budget" >&2
            echo "\trelink [--resources] - relink the component, optionally repackage resources" >&2
            echo "\tbuild-full --approved [--allow-internal] - explicitly permit a broad browser build" >&2
            echo "\tbuild - disabled; cannot accidentally start a broad Chromium build" >&2
            echo "\treset --warm-output --approved - deliberately remove prepared source and output" >&2
    esac
}

he() {
    (__helium_menu "$@")
}

if ! (return 0 2>/dev/null); then
    printf "usage:\n\t$ source dev.sh\n\t$ he\n" 2>&1
    exit 1
else
    if [ "$__helium_loaded" = "" ]; then
        __helium_loaded=1
        PS1="🎈 $PS1"
    fi
fi
