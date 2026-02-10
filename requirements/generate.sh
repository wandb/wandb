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

# Extracts "major.minor" from a version specifier ($1).
function major_minor() {
    echo "$1" | cut -d. -f1,2
}

# Compiles requirements for a Python version ($1) and platform ($2).
function compile() {
    uv pip compile \
        --python-version "$1" \
        --python-platform "$(platform_python_name $2)" \
        requirements/requirements_dev.txt \
        -o "requirements/requirements_dev.$(major_minor $1).$2.txt"
}

# Patch versions needed for 3.8 due to what seems like a uv bug.
compile 3.8.20 darwin
compile 3.8.20 linux

compile 3.9 darwin
compile 3.9 linux
compile 3.9 windows

compile 3.13 darwin
compile 3.13 linux
compile 3.13 windows
