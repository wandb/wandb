#!/usr/bin/env bash
#
# Update development environment
#
# Usage:
#   ./scripts/update-dev-env.sh

set -e

INSTALL=("$@")
DEV_ENV_FILE="scripts/update-dev-env.txt"

# make sure we are running from the core dir
BASE=$(dirname $(dirname $(readlink -f $0)))
cd $BASE

function pinned {
    VERSION=`grep -E ^$1 $DEV_ENV_FILE | cut -d" " -f2`
    if [ "x$VERSION" == "x" ]; then
        echo "ERROR: did not find package $1 in $DEV_ENV_FILE" 1>&2
        exit 1
    fi
    echo $VERSION
}

function install_cmd {
    CMD=`grep -E ^$1 $DEV_ENV_FILE | cut -d" " -f3`
    echo $CMD
}

function command {
    echo $1 | awk -F"/" '{print $NF}'
}

function is_version {
    COMMAND=$1
    VERSION=$2
    CMD_VERSION1=$($COMMAND --version 2>/dev/null | cut -d" " -f2) || true
    CMD_VERSION2=$($COMMAND --version 2>/dev/null | cut -d" " -f4 | sed s/^/v/) || true
    if [ "x$CMD_VERSION1" = "x$VERSION" ]; then
        return 0
    fi
    if [ "x$CMD_VERSION2" = "x$VERSION" ]; then
        return 0
    fi
    return 1
}

function install {
    COMMAND=$(command $SPEC)
    if [[ ${#INSTALL[@]} -gt 0 ]]; then
        MATCH=$(command ${INSTALL[@]})
        if [[ ! "x$MATCH" =~ "x$COMMAND" ]]; then
            return
        fi
    fi
    VERSION=$(pinned $SPEC)
    if is_version $COMMAND $VERSION; then
        echo "[INFO] update-dev-env.sh: Not updating \"$COMMAND\" (Version $VERSION found)"
        return
    fi
    INSTALL_CMD=$(install_cmd $SPEC)
    if [ "x$INSTALL_CMD" != "x" ]; then
        echo "[INFO] update-dev-env.sh: Updating \"$COMMAND\" with script (Want version $VERSION)"
        $INSTALL_CMD $VERSION
    else
        echo "[INFO] update-dev-env.sh: Updating \"$COMMAND\" (Want version $VERSION)"
        go install -v $SPEC@$VERSION
    fi
}

for SPEC in $(grep -E -v '^#' $DEV_ENV_FILE | cut -d" " -f1); do
    install $spec
done
