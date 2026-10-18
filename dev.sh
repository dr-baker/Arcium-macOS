#!/usr/bin/env bash

# Helium's development commands, based on upstream helium-macos dev.sh at the
# commit this checkout's core pin matches (c0056de). Upstream commands keep
# their names and meaning. Arcium's additions are listed in
# docs/development-changes.md; the Python helpers live in devutils/he.

# Resolve this file even when sourced from zsh, where $0 is not the script.
if [ -n "${ZSH_VERSION:-}" ]; then
    _he_script="${(%):-%x}"
elif [ -n "${BASH_SOURCE[0]:-}" ]; then
    _he_script="${BASH_SOURCE[0]}"
else
    _he_script="$0"
fi
_he_tools_dir="$(cd -P "$(dirname "$_he_script")" && pwd)"

# Machine settings live outside the repository. The environment wins.
___helium_load_dev_env() {
    local file="${XDG_CONFIG_HOME:-$HOME/.config}/arcium/dev.env" key value
    [ -f "$file" ] || return 0
    while IFS='=' read -r key value || [ -n "$key" ]; do
        case "$key" in
            *[!A-Z0-9_]*) continue ;;
            HELIUM_*|SISO_*) ;;
            *) continue ;;
        esac
        value="${value%\"}"; value="${value#\"}"; value="${value%\'}"; value="${value#\'}"
        case "$value" in "~/"*) value="$HOME/${value#\~/}" ;; esac
        eval "[ -n \"\${$key+set}\" ]" || export "$key=$value"
    done < "$file"
}
___helium_load_dev_env

# The source worktree supplies patches and recipes; the build dir holds the
# Chromium tree. Both can live anywhere.
_root_dir="$(cd -P "${HELIUM_DEV_WORKTREE:-$_he_tools_dir}" && pwd)"
_build_dir="${HELIUM_BUILD_DIR:-$_root_dir/build}"
case "$_build_dir" in /*) ;; *) _build_dir="$PWD/$_build_dir" ;; esac
[ -d "$_build_dir" ] && _build_dir="$(cd -P "$_build_dir" && pwd)"
# Read by retrieve_and_unpack_resource.sh and setup_python.sh.
export HELIUM_DEV_BUILD_ROOT="$_build_dir"

source "$_root_dir/env.sh"

# build.sh still uses out/Default. Development commands choose their own
# output; the installed daily app keeps the existing optimized cache.
___helium_select_build_mode() {
    case "$1" in
        daily) _out_dir="$_src_dir/out/Default" ;;
        diagnostics) _out_dir="$_src_dir/out/Diagnostics" ;;
        *) echo "error: build mode must be daily or diagnostics" >&2; return 2 ;;
    esac
    _he_build_mode="$1"
    export HELIUM_DEV_BUILD_MODE="$1"
}
___helium_select_build_mode "${HELIUM_DEV_BUILD_MODE:-diagnostics}"

_catalog_dir="$_build_dir/.arcium/patches"
alias quilt='quilt --quiltrc -'
export QUILT_PATCHES="$_catalog_dir"
export QUILT_SERIES="series.merged"
export QUILT_PUSH_ARGS="--color=auto"
export QUILT_DIFF_OPTS="--show-c-function"
export QUILT_PATCH_OPTS="--unified --reject-format=unified"
export QUILT_DIFF_ARGS="-p ab --no-timestamps --no-index --color=auto"
export QUILT_REFRESH_ARGS="-p ab --no-timestamps --no-index"
export QUILT_COLORS="diff_hdr=1;32:diff_add=1;34:diff_rem=1;31:diff_hunk=1;33:diff_ctx=35:diff_cctx=33"
export QUILT_SERIES_ARGS="--color=auto"
export QUILT_PATCHES_ARGS="--color=auto"

___helium_he() {
    PYTHONPATH="$_he_tools_dir/devutils" PYTHONDONTWRITEBYTECODE=1 \
        python3 -m he --worktree "$_root_dir" --build-dir "$_build_dir" --build-mode "$_he_build_mode" "$@"
}

___helium_quilt() {
    command quilt --quiltrc - "$@"
}

# Run a command under the build-dir lock. Nested calls reuse the held lock.
___helium_locked() {
    local label="$1"
    shift
    if [ -n "${HELIUM_LOCK_HELD:-}" ]; then
        "$@"
        return
    fi
    mkdir -p "$_build_dir/.arcium"
    HELIUM_BUILD_DIR="$_build_dir" HELIUM_DEV_WORKTREE="$_root_dir" HELIUM_DEV_BUILD_MODE="$_he_build_mode" \
        ___helium_he lock --label "$label" -- \
        bash -c 'source "$1" >/dev/null || exit 2; shift; set -e; "$@"' bash "$_he_tools_dir/dev.sh" "$@"
}

___helium_is_scratch() {
    [ -f "$_build_dir/.arcium/scratch.json" ]
}

___helium_refuse_in_scratch() {
    if ___helium_is_scratch; then
        echo "error: $_build_dir is a scratch with no build output; hand the patch to the integrator" >&2
        return 1
    fi
}

# Keep temp files and sccache sockets on the build volume when the build dir
# lives outside the checkout.
___helium_use_build_tmpdir() {
    case "$_build_dir" in
        "$_root_dir"/*) return 0 ;;
    esac
    TMPDIR="$(___helium_he tmpdir)" || return
    export TMPDIR
}

___helium_setup_siso() {
    if [ -x "$_siso_path" ]; then
        return
    fi

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

    mkdir -p "$_siso_dir"
    printf '%s\n' "$siso_package $siso_version" |
        "$_depot_tools_dir/cipd" ensure --root "$_siso_dir" --ensure-file -
}

___helium_setup_gn() {
    local OUT_FILE="$_out_dir/args.gn"
    mkdir -p "$_out_dir"
    cat "$_main_repo/flags.gn" "$_root_dir/flags.macos.gn" > "$OUT_FILE"

    if [ -n "${SISO_REAPI_ADDRESS:-}" ]; then
        echo 'use_remoteexec = true' >> "$OUT_FILE"
    elif command -v sccache 2>&1 >/dev/null; then
        echo 'cc_wrapper="sccache"' >> "$OUT_FILE"
    elif command -v ccache 2>&1 >/dev/null; then
        echo 'cc_wrapper="env CCACHE_COMPILERCHECK=content CCACHE_SLOPPINESS=time_macros ccache"' >> "$OUT_FILE"
    else
        echo 'warn: sccache or ccache is not available' >&2
    fi

    local TARGET_CPU="arm64"
    if [[ $_arch == "x86_64" ]]; then
        TARGET_CPU="x64"
    fi

    echo 'target_cpu = "'"$TARGET_CPU"'"' >> "$OUT_FILE"
    echo 'devtools_skip_typecheck = false' >> "$OUT_FILE"
    echo 'use_siso = true' >> "$OUT_FILE"

    sed -i '' s/is_official_build/is_component_build/ "$OUT_FILE"
    sed -i '' '/^[[:space:]]*dcheck_always_on[[:space:]]*=/d; /^[[:space:]]*enable_expensive_dchecks[[:space:]]*=/d' "$OUT_FILE"
    local checks=false
    [ "$_he_build_mode" != diagnostics ] || checks=true
    printf 'dcheck_always_on = %s\nenable_expensive_dchecks = %s\n' "$checks" "$checks" >> "$OUT_FILE"
    ___helium_he stamp gn-defaults
}

# Remote execution through NativeLink is optional: set SISO_REAPI_ADDRESS
# (and optionally SISO_REAPI_INSTANCE), then he configure --refresh-defaults.
# TLS stays on unless RBE_service_no_security=true is set explicitly. With
# SISO_REAPI_ADDRESS unset this writes Chromium's local Siso configuration,
# which also covers full clones made with --nohooks.
___helium_configure_siso() {
    case "${RBE_service_no_security:-false}" in
        true|false) ;;
        *) echo "error: RBE_service_no_security must be true or false" >&2; return 2 ;;
    esac
    if [ -n "${SISO_REAPI_ADDRESS:-}" ]; then
        export SISO_REAPI_INSTANCE="${SISO_REAPI_INSTANCE:-main}"
        python3 "$_src_dir/build/config/siso/configure_siso.py" \
            --reapi_address="$SISO_REAPI_ADDRESS" \
            --reapi_instance="$SISO_REAPI_INSTANCE" \
            --reapi_backend_config_path=nativelink.star
    else
        python3 "$_src_dir/build/config/siso/configure_siso.py" \
            --rbe_instance=projects/rbe-chrome-untrusted/instances/default_instance
    fi
}

___helium_setup_remoteexec_toolchain() {
    [ -n "${SISO_REAPI_ADDRESS:-}" ] || return 0
    python3 "$_src_dir/tools/clang/scripts/update.py" \
        --host-os=linux \
        --output-dir="$_src_dir/third_party/llvm-build/Release+Asserts_linux"
}

___helium_info_pull() {
    local mode="$1"
    # fall back to git clone if tarball is unavailable
    if [ "$mode" = full ]; then
        "$_root_dir/retrieve_and_unpack_resource.sh" -g "$_arch"
    elif "$_root_dir/retrieve_and_unpack_resource.sh" -d -g "$_arch"; then
        mode=lite
    else
        "$_root_dir/retrieve_and_unpack_resource.sh" -g "$_arch"
        mode=full
    fi
    ___helium_he acquisition record --source-mode "$mode"
    _he_source_mode="$mode"

    mkdir -p "$_out_dir"
    cd "$_src_dir"
}

___helium_configure() {
    if [ "$#" -gt 1 ] || { [ "$#" -eq 1 ] && [ "$1" != --refresh-defaults ]; }; then
        echo "usage: he configure [--refresh-defaults]" >&2
        return 2
    fi
    ___helium_refuse_in_scratch
    ___helium_use_build_tmpdir
    if [ "${1:-}" = --refresh-defaults ] || [ ! -f "$_out_dir/args.gn" ]; then
        ___helium_setup_gn
    fi
    cd "$_src_dir"
    ___helium_setup_siso
    ___helium_configure_siso
    ___helium_setup_remoteexec_toolchain
    ___helium_he test-assets
    "$_root_dir/devutils/setup_dawn_go.sh" "$_src_dir" "$_depot_tools_dir" "$_arch"
    python3 ./tools/gn/bootstrap/bootstrap.py -o "$_out_dir/gn" --skip-generate-buildfiles
    "$_out_dir/gn" gen "$_out_dir" --fail-on-unused-args --export-compile-commands
}

___helium_toolchain() {
    "$_root_dir/retrieve_and_unpack_resource.sh" -t
}

___helium_resources() {
    python3 "$_main_repo/utils/generate_resources.py" "$_main_repo/resources/generate_resources.txt" "$_main_repo/resources"
    python3 "$_main_repo/utils/replace_resources.py" "$_root_dir/resources/platform_resources.txt" "$_root_dir/resources" "$_src_dir"
    python3 "$_main_repo/utils/replace_resources.py" "$_main_repo/resources/helium_resources.txt" "$_main_repo/resources" "$_src_dir"
    ___helium_he stamp resources
}

___helium_version() {
    python3 "$_main_repo/utils/helium_version.py" \
        --tree "$_main_repo" \
        --platform-tree "$_root_dir" \
        --chromium-tree "$_src_dir"
    ___helium_he stamp version
}

# he presetup [--full-source] [--force]
___helium_setup_presetup() {
    local mode=auto force=false argument
    for argument in "$@"; do
        case "$argument" in
            --full-source) mode=full ;;
            --force) force=true ;;
            *) echo "usage: he presetup|setup [--full-source] [--force]" >&2; return 2 ;;
        esac
    done
    ___helium_refuse_in_scratch
    if [ -d "$_src_dir/out" ]; then
        echo "$_src_dir/out already exists" >&2
        return
    fi
    $force || ___helium_he space --need-gib 100
    ___helium_use_build_tmpdir

    rm -rf "$_src_dir" && mkdir -p "$_download_cache" "$_src_dir"
    ___helium_he timestamps discard --reason "fresh source" || true
    rm -f "$_build_dir/.arcium/applied.json"

    ___helium_info_pull "$mode"
    ___helium_he gclient-marker
    # Full-source build dirs keep Chromium's test data for browser_tests.
    if [ "$_he_source_mode" != full ]; then
        python3 "$_main_repo/utils/prune_binaries.py" "$_src_dir" "$_main_repo/pruning.list"
    fi
    ___helium_toolchain
    ___helium_resources
    ___helium_setup_gn
    ___helium_version
}

___helium_setup() {
    ___helium_setup_presetup "$@"
    ___helium_patches_merge
    ___helium_quilt_push
    ___helium_configure
}

___helium_reset() {
    # Write refreshed lane patches back first; a conflict stops the reset.
    ___helium_patches_unmerge
    ___helium_he timestamps discard --reason reset || true
    rm -f "$_build_dir/.arcium/applied.json" "$_build_dir/.arcium/stamps.json"
    rm "$_subs_cache" || true
    rm "$_namesubs_cache" || true
    if mv "$_src_dir" "${_src_dir}x"; then
        rm -rf "${_src_dir}x" &
    fi
}

___helium_name_substitution() {
    if [ "$1" = "nameunsub" ]; then
        python3 "$_main_repo/utils/name_substitution.py" --unsub \
            -t "$_src_dir" --backup-path "$_namesubs_cache"
    elif [ "$1" = "namesub" ]; then
        if [ -f "$_namesubs_cache" ]; then
            echo "$_namesubs_cache exists, are you sure you want to do this?" >&2
            echo "if yes, then delete the $_namesubs_cache file" >&2
            return
        fi

        python3 "$_main_repo/utils/name_substitution.py" --sub \
            -t "$_src_dir" --backup-path "$_namesubs_cache"
    else
        echo "unknown action: $1" >&2
        return
    fi
}

___helium_apply_translations() {
    python3 "$_main_repo/utils/i18n_apply.py" -t "$_src_dir"
}

___helium_generate_translations() {
    python3 "$_main_repo/devutils/i18n.py" generate
}

___helium_substitution() {
    if [ "$1" = "unsub" ]; then
        python3 "$_main_repo/utils/domain_substitution.py" revert \
            -c "$_subs_cache" "$_src_dir"

        ___helium_name_substitution nameunsub
    elif [ "$1" = "sub" ]; then
        if [ -f "$_subs_cache" ]; then
            echo "$_subs_cache exists, are you sure you want to do this?" >&2
            echo "if yes, then delete the $_subs_cache file" >&2
            return
        fi

        ___helium_name_substitution namesub

        python3 "$_main_repo/utils/domain_substitution.py" apply \
            -r "$_main_repo/domain_regex.list" \
            -f "$_main_repo/domain_substitution.list" \
            -c "$_subs_cache" \
            "$_src_dir"
    else
        echo "unknown action: $1" >&2
        return
    fi
}

# he build [--jobs N] [TARGET...]
___helium_build() {
    local -a targets=() jobs=() guard=()
    while [ "$#" -gt 0 ]; do
        case "$1" in
            --approved|--edge-budget)
                if [ "${HELIUM_AGENT_MODE:-}" != 1 ]; then
                    echo "error: $1 belongs to he agent build" >&2; return 2
                fi
                if [ "$1" = --approved ]; then guard+=(--approved); shift; else guard+=(--edge-budget "$2"); shift 2; fi
                ;;
            --jobs)
                case "${2:-}" in ''|*[!0-9]*|0) echo "usage: he build [--jobs N] [TARGET...]" >&2; return 2 ;; esac
                if grep -Eq '^[[:space:]]*use_siso[[:space:]]*=[[:space:]]*true' "$_out_dir/args.gn" 2>/dev/null; then
                    jobs=("-local_jobs=$2")
                else
                    jobs=(-j "$2")
                fi
                shift 2
                ;;
            *) targets+=("$1"); shift ;;
        esac
    done
    ___helium_refuse_in_scratch
    if [ "${HELIUM_AGENT_MODE:-}" = 1 ]; then
        # Explicit targets, no pending snapshot, a clean he check, and a
        # dry-run plan within the edge budget (see docs/agent-workflow.md).
        ___helium_he agent-guard "${guard[@]}" "${targets[@]}" >/dev/null
    fi
    [ "${#targets[@]}" -gt 0 ] || targets=(chrome chromedriver)
    ___helium_he acquisition require
    # Building popped source means the snapshot can never be restored safely.
    ___helium_he timestamps discard --reason "built while patches were popped"
    ___helium_he check --warn
    ___helium_use_build_tmpdir
    [ -z "${SISO_REAPI_ADDRESS:-}" ] || export SISO_REAPI_INSTANCE="${SISO_REAPI_INSTANCE:-main}"
    cd "$_src_dir"
    SISO_PATH="$_siso_path" python3 "$_depot_tools_dir/autoninja.py" \
    -k 0 "${jobs[@]}" -C "$_out_dir" "${targets[@]}"
    ___helium_he completed-build -- "${targets[@]}"
}

___helium_run() {
    ___helium_refuse_in_scratch
    ___helium_he verify-build
    "$_out_dir/Helium.app/Contents/MacOS/Helium" \
    --user-data-dir="$HOME/Library/Application Support/net.imput.helium.dev" \
    --enable-ui-devtools \
    --use-mock-keychain \
    --disable-features=DialMediaRouteProvider
}

___helium_pull() {
    if [ -f "$_subs_cache" ]; then
        echo "source files are substituted, please run 'he unsub' first" >&2
        return 1
    fi

    # Stop before touching git or the catalog if lane edits cannot be saved.
    ___helium_quilt_pop
    ___helium_patches_unmerge

    for dir in "$_root_dir" "$_main_repo"; do
        git -C "$dir" stash \
        && git -C "$dir" fetch \
        && git -C "$dir" rebase origin/main \
        && git -C "$dir" stash pop \
        || true
    done

    ___helium_patches_merge
    ___helium_quilt_push
}

___helium_patches_merge() {
    ___helium_he merge "$@"
}

___helium_patches_unmerge() {
    ___helium_he unmerge
}

# he push [--refresh]: strict by default; --refresh is upstream's behavior.
___helium_quilt_push() {
    # Quilt's own --fuzz=N option hangs on macOS; pass the limit to patch(1).
    local patch_opts="$QUILT_PATCH_OPTS --fuzz=0"
    local -a mode=()
    case "${1:-}" in
        '') ;;
        --refresh) mode=(--refresh); patch_opts="$QUILT_PATCH_OPTS" ;;
        *) echo "usage: he push [--refresh]" >&2; return 2 ;;
    esac
    ___helium_he acquisition require
    ___helium_he mark-before-push
    cd "$_src_dir"
    local status=0
    QUILT_PATCH_OPTS="$patch_opts" ___helium_quilt push -a "${mode[@]}" </dev/null || status=$?
    ___helium_he sync-applied
    # Quilt exits 2 when every patch is already applied.
    if [ "$status" -ne 0 ] && [ "$status" -ne 2 ]; then
        echo "error: push stopped at the patch above. Fix it (quilt push -f, edit, quilt refresh, he save-patch), then he push again" >&2
        return "$status"
    fi
    ___helium_he timestamps restore
}

# he pop [PATCH]: without PATCH, unapply everything.
___helium_quilt_pop() {
    [ "$#" -le 1 ] || { echo "usage: he pop [PATCH]" >&2; return 2; }
    ___helium_he timestamps capture
    cd "$_src_dir"
    local status=0
    if [ "$#" -eq 1 ]; then
        ___helium_quilt pop "$1" </dev/null || status=$?
    else
        ___helium_quilt pop -a </dev/null || status=$?
    fi
    ___helium_he sync-applied
    # Quilt exits 2 when nothing is applied.
    [ "$status" -eq 0 ] || [ "$status" -eq 2 ] || return "$status"
}

___helium_replay() {
    ___helium_quilt_pop
    ___helium_quilt_push
}

___helium_save_patch() {
    ___helium_he save-patch "$@"
}

___helium_check() {
    ___helium_he check "$@"
}

___helium_locate() {
    ___helium_he locate "$@"
}

# he scratch NAME | he scratch --remove NAME
___helium_scratch() {
    if [ "${1:-}" = --remove ] && [ "$#" -eq 2 ]; then
        ___helium_he scratch remove "$2"
        return
    fi
    [ "$#" -eq 1 ] && [ "${1#-}" = "$1" ] || { echo "usage: he scratch NAME | he scratch --remove NAME" >&2; return 2; }
    local root
    root="$(___helium_he scratch create "$1")"
    echo "scratch ready: $root"
    echo "use it from a worker's worktree with:"
    echo "  HELIUM_BUILD_DIR='$root' HELIUM_DEV_WORKTREE=<worker worktree> source '$_he_tools_dir/dev.sh'"
}

___helium_validate() {
    if [ "$1" = "config" ]; then
        python3 "$_main_repo/devutils/validate_config.py"
    elif [ "$1" = "patches" ]; then
        if [ ! -f "$_catalog_dir/series.merged" ]; then
            echo "$_catalog_dir/series.merged doesn't exist. did you forget to merge?" >&2
            return 1
        fi
        python3 "$_main_repo/devutils/validate_patches.py" \
            -l "$_src_dir" \
            -s "$_catalog_dir/series.merged" \
            -p "$_catalog_dir"
    elif [ "$1" = "series" ]; then
        python3 "$_he_tools_dir/devutils/check_patch_files.py" -p "$_main_repo/patches" &&
            python3 "$_he_tools_dir/devutils/check_patch_files.py" -p "$_root_dir/patches"
    else
        echo "unknown validate action. usage: he validate <config|patches|series>" >&2
    fi
}

___helium_format() {
    cd "$_src_dir"
    ___helium_quilt diff | "$_src_dir/third_party/clang-format/script/clang-format-diff.py" \
    -p1 -i -style=file
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

___helium_tidy() {
    ___helium_find_tidy_diff || return;
    ___helium_strip_compile_commands;
    cd "$_src_dir"
    ___helium_quilt diff | "$_tidy_diff_script" \
        -regex '.*\.(cc|mm)' \
        -use-color \
        -p1 \
        -path "$_out_dir" \
        -quiet \
        -j$(nproc)
}

___helium_lint() {
    ___helium_format;
    ___helium_tidy;
}

# he run [--profile NAME [--new] [--labeled] [--empty | --seed-from installed|dev|arcium|PATH]]
#        [--json] [browser flags...]
# Without profile options this is upstream's he run.
___helium_run_profile() {
    ___helium_refuse_in_scratch
    local -a options=() passthrough=()
    while [ "$#" -gt 0 ]; do
        case "$1" in
            --profile) options+=(--profile "$2"); shift 2 ;;
            --profile=*) options+=(--profile "${1#*=}"); shift ;;
            --seed-from) options+=(--seed-from "$2"); shift 2 ;;
            --new|--labeled|--empty|--json) options+=("$1"); shift ;;
            --fresh|--fresh=*|--isolated|--isolated=*)
                echo "error: ${1%%=*} was replaced by --profile NAME (add --new for a new profile, --empty for a blank one)" >&2
                return 2 ;;
            *) passthrough+=("$1"); shift ;;
        esac
    done
    ___helium_he run "${options[@]}" -- "${passthrough[@]}"
}

___helium_stop() {
    case "${1:-}" in
        --profile) ___helium_he stop --profile "$2" ;;
        '') ___helium_he stop ;;
        *) echo "usage: he stop [--profile NAME]" >&2; return 2 ;;
    esac
}

# he arcium [--no-build] [--no-launch] [--json] | he arcium status [--json]
___helium_arcium() {
    ___helium_select_build_mode daily
    local action=install build=true argument
    local -a options=()
    for argument in "$@"; do
        case "$argument" in
            status) action=status ;;
            --no-build) build=false ;;
            --no-launch|--json|--approved) options+=("$argument") ;;
            *) echo "usage: he arcium [--no-build] [--no-launch] [--json] | he arcium status [--json]" >&2; return 2 ;;
        esac
    done
    if [ "$action" = install ]; then
        ___helium_refuse_in_scratch
        if $build; then
            if ! ___helium_he configuration-current; then
                ___helium_configure --refresh-defaults
            fi
            ___helium_build chrome
        fi
    fi
    PYTHONPATH="$_he_tools_dir/devutils" PYTHONDONTWRITEBYTECODE=1 \
        python3 -m arcium.install --build-dir "$_build_dir" "$action" "${options[@]}"
}

# Commands that change the source tree, build output, or build-dir state run
# under the build-dir lock; read-only commands do not.
__helium_dispatch() {
    set -e
    local command="$1"
    shift
    case "$command" in
        setup) ___helium_setup "$@";;
        presetup) ___helium_setup_presetup "$@";;
        configure) ___helium_configure "$@";;
        resources) ___helium_resources;;
        version) ___helium_version;;

        sub|unsub) ___helium_substitution "$command";;
        namesub|nameunsub) ___helium_name_substitution "$command";;
        translate) ___helium_apply_translations;;
        transgen) ___helium_generate_translations;;

        merge) ___helium_patches_merge "$@";;
        unmerge) ___helium_patches_unmerge;;
        push) ___helium_quilt_push "$@";;
        pop) ___helium_quilt_pop "$@";;
        replay) ___helium_replay;;
        save-patch) ___helium_save_patch "$@";;
        pull) ___helium_pull;;
        scratch) ___helium_scratch "$@";;
        scratch-pull) ___helium_he scratch-pull "$@";;

        format) ___helium_format;;
        tidy) ___helium_tidy;;
        lint) ___helium_lint;;

        build) ___helium_build "$@";;
        reset) ___helium_reset;;
        run) ___helium_run_profile "$@";;
        arcium) ___helium_arcium "$@";;
    esac
}

__helium_menu() {
    set -e
    local command="${1:-}" argument selected="${HELIUM_DEV_BUILD_MODE:-diagnostics}" explicit_mode="" after_separator=false
    local -a filtered=()
    case "$command" in
        setup|presetup|configure|build|run|check|tidy|lint)
            shift
            for argument in "$@"; do
                if $after_separator; then
                    filtered+=("$argument")
                else
                    case "$argument" in
                        --daily|--diagnostics)
                            selected="${argument#--}"
                            if [ -n "$explicit_mode" ] && [ "$explicit_mode" != "$selected" ]; then
                                echo "error: choose --daily or --diagnostics, not both" >&2; return 2
                            fi
                            explicit_mode="$selected" ;;
                        --) after_separator=true; filtered+=("$argument") ;;
                        *) filtered+=("$argument") ;;
                    esac
                fi
            done
            ___helium_select_build_mode "$selected"
            set -- "$command" "${filtered[@]}" ;;
        arcium) ___helium_select_build_mode daily ;;
    esac
    case $1 in
        setup|presetup|configure|resources|version|sub|unsub|namesub|nameunsub|translate|transgen|\
        merge|unmerge|push|pop|replay|save-patch|pull|scratch|scratch-pull|format|tidy|lint|build|reset)
            ___helium_locked "$1" __helium_dispatch "$@";;

        run)
            if [ "$#" -eq 1 ]; then
                ___helium_run
            else
                ___helium_locked run __helium_dispatch "$@"
            fi;;
        stop) shift; ___helium_stop "$@";;
        arcium)
            if [ "${2:-}" = status ]; then
                shift; ___helium_arcium "$@"
            else
                ___helium_locked arcium __helium_dispatch "$@"
            fi;;
        agent)
            # The agent prefix: any command, with stricter build and arcium.
            if [ "$#" -lt 2 ]; then
                echo "usage: he agent COMMAND [ARGS...]; see docs/agent-workflow.md" >&2
                return 2
            fi
            shift
            export HELIUM_AGENT_MODE=1
            __helium_menu "$@";;

        validate) ___helium_validate "$2";;
        check) shift; ___helium_check "$@";;
        locate) shift; ___helium_locate "$@";;
        *)
            echo "usage: he <command>" >&2
            echo "\tsetup [--full-source] - sets up the dev environment fully for the first time" >&2
            echo "\t         equivalent of: [presetup, merge, push, configure]" >&2
            echo "\tpresetup [--full-source] [--force] - downloads sources, sets up GN, and prepares third-party dependencies" >&2
            echo "\tconfigure [--daily|--diagnostics] [--refresh-defaults] - generates build configuration and tools" >&2
            echo "\tresources - generates and copies helium resources (such as icons)" >&2
            echo "\tversion - writes the current version metadata into the Chromium tree" >&2

            echo "\n" >&2
            echo "\tsub - apply google domain and name substitutions" >&2
            echo "\tunsub - undo google domain and name substitutions" >&2
            echo "\tnamesub - apply only name substitutions" >&2
            echo "\tnameunsub - undo only name substitutions" >&2
            echo "\ttranslate - apply translations from i18n directory" >&2
            echo "\ttransgen - generate source strings for translation" >&2

            echo "\n" >&2
            echo "\tmerge [--discard] - merges all patches into the build dir's catalog" >&2
            echo "\tunmerge - writes catalog edits back and unmerges all patches" >&2
            echo "\tpush [--refresh] - applies all patches; stops on fuzz unless --refresh" >&2
            echo "\tpop [PATCH] - undoes all patches, or those after PATCH" >&2
            echo "\treplay - pop and push the whole series" >&2
            echo "\tsave-patch [--style p1|ab] - refreshes the top patch into its owning repository" >&2
            echo "\tpull - undoes all patches, pulls from git, redoes all patches" >&2
            echo "\tscratch NAME | --remove NAME - copy-on-write source for patch authoring" >&2
            echo "\tscratch-pull PATH... - (in a scratch) clone files no patch owns yet before quilt add" >&2

            echo "\n" >&2
            echo "\tcheck [--json] - reports drift between patches, records, and the source tree" >&2
            echo "\tlocate QUERY - finds which patch owns a file or symbol" >&2
            echo "\tvalidate config - validates the build configuration" >&2
            echo "\tvalidate patches - validates that patches are applied correctly" >&2
            echo "\tvalidate series - checks the consistency of the series file" >&2
            echo "\tformat - formats the topmost patch according to Chromium coding style" >&2
            echo "\ttidy - runs clang-tidy on the topmost patch" >&2
            echo "\tlint - he format + he tidy" >&2

            echo "\n" >&2
            echo "\tbuild [--daily|--diagnostics] [--jobs N] [TARGET...] - builds a diagnostic binary by default" >&2
            echo "\trun - runs a development build of helium with dev data dir & ui devtools enabled" >&2
            echo "\trun [--daily|--diagnostics] --profile NAME [--new] [--labeled] [--empty | --seed-from SRC] [flags] - runs Helium Dev on a named profile" >&2
            echo "\tstop [--profile NAME] - quits the Helium Dev app using that profile" >&2
            echo "\tarcium [--no-build] - builds and installs /Applications/Arcium.app, restarting it if running" >&2
            echo "\tarcium status - shows the installed app's identity, signature, and process" >&2
            echo "\tagent COMMAND - runs any command with agent guards; see docs/agent-workflow.md" >&2
            echo "\treset - nukes everything" >&2
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
