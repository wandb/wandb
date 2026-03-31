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

# Maps platform.system() output ($1) to a platform understood by uv.
function platform_python_name() {
    if [ "$1" = darwin ]; then
        echo macos
    else
        echo "$1"
    fi
}

# Compiles requirements for a Python version ($1) and platform ($2).
function compile() {
    uv pip compile "${PIP_COMPILE_ARGS[@]}" \
        --python-version "$1" \
        --python-platform "$(platform_python_name $2)" \
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
