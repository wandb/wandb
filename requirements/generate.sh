#!/bin/bash

set -e

function print_help() {
    echo "Usage: generate.sh [--upgrade]"
    echo
    echo "Pass --upgrade or -U to upgrade all requirements."
    echo "Pass --upgrade-package <package> or -P to upgrade specific packages."
    echo "  Upgrading specific packages can be desirable if some upgrades"
    echo "  have security or license issues. It is preferred to use this"
    echo "  mechanism instead of adding pins in the requirements file."
    echo
    echo "  Unfortunately, uv does not provide an '--upgrade-except' option yet:"
    echo "  https://github.com/astral-sh/uv/issues/7177"
    echo
    echo "By default, this will apply any new requirements_dev.txt constraints"
    echo "while trying to preserve any currently pinned versions."
}

PIP_COMPILE_ARGS=()

# Parse arguments.
while [[ "$#" -gt 0 ]]; do
    case "$1" in
        --upgrade|-U)
            PIP_COMPILE_ARGS+=( "--upgrade" )
            ;;

        --upgrade-package|-P)
            if [[ "$#" -lt 2 ]]; then
                echo "The --upgrade-package / -P option requires an argument."
                exit 1
            fi

            PIP_COMPILE_ARGS+=( "--upgrade-package" "$2" )
            shift  # Pop the extra argument.
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
        --exclude-newer "1w" \
        --python-version "$1" \
        --python-platform "$(platform_python_name $2)" \
        requirements/requirements_dev.txt \
        -o "requirements/requirements_dev.$1.$2.txt" \
        >/dev/null  # https://github.com/astral-sh/uv/issues/3701
}

compile 3.10 darwin
compile 3.10 linux
compile 3.10 windows

compile 3.13 darwin
compile 3.13 linux
compile 3.13 windows
