#!/bin/bash
set -eou pipefail

die () {
    echo >&2 "$@"
    echo >&2 "usage: ./verify_sweeps.sh SWEEPS_REF"
    exit 1
}

# absolute path to the client root directory
CLIENT_ROOT="$( cd -- "$(dirname "$0")" >/dev/null 2>&1 ; pwd -P )"/..
SWEEPS_REF=`cat $CLIENT_ROOT/.sweeps_ref`

# check out sweeps to a temporary directory
TMPDIR=`mktemp -d`
cd $TMPDIR
git clone --quiet https://github.com/wandb/sweeps 
cd sweeps

# check it out to the requested ref
git checkout --quiet $SWEEPS_REF

# todo: this will skip platform-specific specifiers in requirements
#       used to bypass a dependency clash on a Mac with the Apple M1 chip
#       Remove once https://wandb.atlassian.net/browse/WB-8120 is resolved
DIFF=$(echo -e "$(diff <(cat requirements.txt) <(grep -o '^[^;]*' $CLIENT_ROOT/requirements.sweeps.txt))")
if [ "$DIFF" != "" ]; then
    echo >&2 "ERROR: vendored sweeps' requirements do not match ref $SWEEPS_REF"
    echo >&2 "$DIFF"
    echo >&2 "please run `make vendor-sweeps ref=$SWEEPS_REF` and commit the result"
    exit 1
fi

if ! diff -r src/sweeps $CLIENT_ROOT/wandb/sweeps; then
    echo >&2 "ERROR: vendored sweeps does not match ref $SWEEPS_REF"
    echo >&2 "please run `make vendor-sweeps ref=$SWEEPS_REF` and commit the result"
    exit 1
fi

echo OK
