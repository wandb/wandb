#!/bin/bash
set -eou pipefail

die () {
    echo >&2 "$@"
    echo >&2 "usage: ./vendor_sweeps.sh SWEEPS_COMMIT_HASH"
    exit 1
}

[ "$#" -eq 1 ] || die "1 argument required, $# provided"

# absolute path to the current file
CLIENT_ROOT="$( cd -- "$(dirname "$0")" >/dev/null 2>&1 ; pwd -P )"/..
TMPDIR=`mktemp -d`
cd $TMPDIR
git clone https://github.com/wandb/sweeps
cd sweeps
git checkout $1
if [ -d $CLIENT_ROOT/wandb/sweeps ]; then
    rm -rf $CLIENT_ROOT/wandb/sweeps
fi
cp -rv src/sweeps $CLIENT_ROOT/wandb


