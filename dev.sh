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
            HELIUM_[A-Z_]*|SISO_[A-Z_]*) ;;
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
        python3 -m he --worktree "$_root_dir" --build-dir "$_build_dir" "$@"
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
    HELIUM_BUILD_DIR="$_build_dir" HELIUM_DEV_WORKTREE="$_root_dir" \
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

    if command -v sccache 2>&1 >/dev/null; then
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
    ___helium_he stamp gn-defaults
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
    if [ "${1:-}" = --refresh-defaults ]; then
        ___helium_setup_gn
    fi
    cd "$_src_dir"
    ___helium_setup_siso
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
    ___helium_patches_unmerge || true
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
    local -a targets=() jobs=()
    while [ "$#" -gt 0 ]; do
        case "$1" in
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
    [ "${#targets[@]}" -gt 0 ] || targets=(chrome chromedriver)
    ___helium_refuse_in_scratch
    ___helium_he acquisition require
    # Building popped source means the snapshot can never be restored safely.
    ___helium_he timestamps discard --reason "built while patches were popped"
    ___helium_he check --warn
    ___helium_use_build_tmpdir
    cd "$_src_dir"
    SISO_PATH="$_siso_path" python3 "$_depot_tools_dir/autoninja.py" \
    -k 0 "${jobs[@]}" -C "$_out_dir" "${targets[@]}"
}

___helium_run() {
    ___helium_refuse_in_scratch
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

    ___helium_quilt_pop || true
    ___helium_patches_unmerge || true

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
    ___helium_he merge
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
    ___helium_he check
}

___helium_locate() {
    PYTHONDONTWRITEBYTECODE=1 python3 "$_he_tools_dir/devutils/patch_lookup.py" \
        --worktree "$_root_dir" --build-root "$_build_dir" --source "$_src_dir" "$@"
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

        merge) ___helium_patches_merge;;
        unmerge) ___helium_patches_unmerge;;
        push) ___helium_quilt_push "$@";;
        pop) ___helium_quilt_pop "$@";;
        replay) ___helium_replay;;
        save-patch) ___helium_save_patch "$@";;
        pull) ___helium_pull;;
        scratch) ___helium_scratch "$@";;

        format) ___helium_format;;
        tidy) ___helium_tidy;;
        lint) ___helium_lint;;

        build) ___helium_build "$@";;
        reset) ___helium_reset;;
    esac
}

__helium_menu() {
    set -e
    case $1 in
        setup|presetup|configure|resources|version|sub|unsub|namesub|nameunsub|translate|transgen|\
        merge|unmerge|push|pop|replay|save-patch|pull|scratch|format|tidy|lint|build|reset)
            ___helium_locked "$1" __helium_dispatch "$@";;

        validate) ___helium_validate "$2";;
        check) ___helium_check;;
        locate) shift; ___helium_locate "$@";;
        run) ___helium_run;;
        *)
            echo "usage: he <command>" >&2
            echo "\tsetup [--full-source] - sets up the dev environment fully for the first time" >&2
            echo "\t         equivalent of: [presetup, merge, push, configure]" >&2
            echo "\tpresetup [--full-source] [--force] - downloads sources, sets up GN, and prepares third-party dependencies" >&2
            echo "\tconfigure [--refresh-defaults] - generates build configuration and tools" >&2
            echo "\tresources - generates and copies helium resources (such as icons)" >&2
            echo "\tversion - stamps the Chromium tree with the current version" >&2

            echo "\n" >&2
            echo "\tsub - apply google domain and name substitutions" >&2
            echo "\tunsub - undo google domain and name substitutions" >&2
            echo "\tnamesub - apply only name substitutions" >&2
            echo "\tnameunsub - undo only name substitutions" >&2
            echo "\ttranslate - apply translations from i18n directory" >&2
            echo "\ttransgen - generate source strings for translation" >&2

            echo "\n" >&2
            echo "\tmerge - merges all patches into the build dir's catalog" >&2
            echo "\tunmerge - writes catalog edits back and unmerges all patches" >&2
            echo "\tpush [--refresh] - applies all patches; stops on fuzz unless --refresh" >&2
            echo "\tpop [PATCH] - undoes all patches, or those after PATCH" >&2
            echo "\treplay - pop and push the whole series" >&2
            echo "\tsave-patch [--style p1|ab] - refreshes the top patch into its owning repository" >&2
            echo "\tpull - undoes all patches, pulls from git, redoes all patches" >&2
            echo "\tscratch NAME | --remove NAME - copy-on-write source for patch authoring" >&2

            echo "\n" >&2
            echo "\tcheck - reports drift between patches, records, and the source tree" >&2
            echo "\tlocate QUERY - finds which patch owns a file or symbol" >&2
            echo "\tvalidate config - validates the build configuration" >&2
            echo "\tvalidate patches - validates that patches are applied correctly" >&2
            echo "\tvalidate series - checks the consistency of the series file" >&2
            echo "\tformat - formats the topmost patch according to Chromium coding style" >&2
            echo "\ttidy - runs clang-tidy on the topmost patch" >&2
            echo "\tlint - he format + he tidy" >&2

            echo "\n" >&2
            echo "\tbuild [--jobs N] [TARGET...] - builds a development binary" >&2
            echo "\trun - runs a development build of helium with dev data dir & ui devtools enabled" >&2
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
