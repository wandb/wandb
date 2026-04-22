#!/bin/bash

set -e

function print_help() {
    echo "Usage: generate.sh [--upgrade]"
    echo
    echo "Pass --upgrade to upgrade all requirements."
    echo
    echo "Otherwise, this will apply any new requirements_dev.txt constraints"
    echo "while trying to preserve any currently pinned versions."
}

PIP_COMPILE_ARGS=()

# Parse arguments.
while [[ "$#" -gt 0 ]]; do
    case "$1" in
        --upgrade)
            PIP_COMPILE_ARGS+=( "--upgrade" )
            ;;

        --help)
            print_help
            exit 0
            ;;

        *)
            echo "Unknown argument: $1" >&2
            print_help >&2
            exit 1
            ;;
    esac

    shift
done

# Maps a Python version ($1) and platform.system() output ($2) to a platform
# understood by uv.
function uv_python_platform() {
    if [ "$2" = darwin ]; then
        echo macos
    elif [ "$1" = 3.13 ] && [ "$2" = linux ]; then
        # rdkit only publishes CPython 3.13 Linux wheels for manylinux_2_28.
        echo x86_64-manylinux_2_28
    else
        echo "$2"
    fi
}

# Compiles requirements for a Python version ($1) and platform ($2).
function compile() {
    uv pip compile "${PIP_COMPILE_ARGS[@]}" \
        --python-version "$1" \
        --python-platform "$(uv_python_platform "$1" "$2")" \
        requirements/requirements_dev.txt \
        -o "requirements/requirements_dev.$1.$2.txt" \
        >/dev/null  # https://github.com/astral-sh/uv/issues/3701
}

compile 3.9 darwin
compile 3.9 linux
compile 3.9 windows

compile 3.13 darwin
compile 3.13 linux
compile 3.13 windows
