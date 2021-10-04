#!/bin/bash
set -eou pipefail

die () {
    echo >&2 "$@"
    echo >&2 "usage: ./vendor_sweeps.sh SWEEPS_REF"
    exit 1
}

[ "$#" -eq 1 ] || die "1 argument required, $# provided"

# absolute path to the client root directory
CLIENT_ROOT="$( cd -- "$(dirname "$0")" >/dev/null 2>&1 ; pwd -P )"/..

# check out sweeps to a temporary directory
TMPDIR=`mktemp -d`
cd $TMPDIR
git clone https://github.com/wandb/sweeps
cd sweeps

# check it out to the requested ref
git checkout $1

# move it to the client repo
if [ -d $CLIENT_ROOT/wandb/sweeps ]; then
    rm -rf $CLIENT_ROOT/wandb/sweeps
fi
cp -rv src/sweeps $CLIENT_ROOT/wandb
cp -rv requirements.txt $CLIENT_ROOT/requirements.sweeps.txt

# record the pegged ref
echo $1 > $CLIENT_ROOT/.sweeps_ref
