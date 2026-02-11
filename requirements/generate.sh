#!/bin/bash

set -e

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
    uv pip compile \
        --python-version "$1" \
        --python-platform "$(platform_python_name $2)" \
        requirements/requirements_dev.txt \
        -o "requirements/requirements_dev.$1.$2.txt"
}

compile 3.9 darwin
compile 3.9 linux
compile 3.9 windows

compile 3.13 darwin
compile 3.13 linux
compile 3.13 windows
