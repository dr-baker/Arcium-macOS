#!/usr/bin/env bash

# Prepare the Python environment used by Arcium-macOS tooling.
#
# The caller must set _root_dir to the active worktree before sourcing this
# file. The environment lives in the selected build lane.

_python_env_dir="${HELIUM_DEV_PYTHON_ENV:-${HELIUM_DEV_BUILD_ROOT:-$_root_dir/build}/python-env}"
_python_env_bin="$_python_env_dir/bin/python3"
_python_requirements="$_root_dir/requirements-dev.txt"

if [ -x "$_python_env_bin" ]; then
    case ":${PATH}:" in
        *":$_python_env_dir/bin:"*) ;;
        *) export PATH="$_python_env_dir/bin:$PATH" ;;
    esac
fi

___helium_setup_python() {
    if [ -z "${_python_env_bin:-}" ] || [ -z "${_python_requirements:-}" ]; then
        echo "error: setup_python.sh requires _root_dir" >&2
        return 1
    fi

    if [ ! -f "$_python_requirements" ]; then
        echo "error: missing Python dependency file: $_python_requirements" >&2
        return 1
    fi

    if [ ! -x "$_python_env_bin" ]; then
        local _python_base
        _python_base="${HELIUM_DEV_PYTHON:-$(command -v python3 || true)}"
        if [ -z "$_python_base" ]; then
            echo "error: python3 is required to create $_python_env_dir" >&2
            return 1
        fi

        if [ -e "$_python_env_dir" ]; then
            echo "error: incomplete Python environment at $_python_env_dir" >&2
            echo "remove that worktree-local directory and retry" >&2
            return 1
        fi

        echo "creating worktree-local Python environment at $_python_env_dir"
        mkdir -p "$(dirname "$_python_env_dir")"
        "$_python_base" -m venv "$_python_env_dir" || return
    fi

    if ! "$_python_env_bin" -c 'import PIL, httplib2, requests' >/dev/null 2>&1; then
        echo "installing Arcium Python dependencies from $_python_requirements"
        "$_python_env_bin" -m pip install \
            --disable-pip-version-check \
            --no-input \
            --requirement "$_python_requirements" || return
    fi

    export PATH="$_python_env_dir/bin:$PATH"
}
