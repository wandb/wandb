#!/usr/bin/env bash

################################################################################
# Exits with a non-zero code if the cognitive complexity of any Go function
# increased beyond the limit.
#
# Usage:
#   run-gocognit.sh path/to/file1.go path/to/file2.go ...
#
# Defaults to comparing HEAD^ to HEAD, but uses PRE_COMMIT_FROM_REF
# and PRE_COMMIT_TO_REF if they are set. For merge commits, HEAD^ is the first
# parent and conventionally corresponds to the target branch of the merge.
################################################################################
set -eu -o pipefail
MAX_COMPLEXITY=15

if [[ $# -le 0 ]]; then
    echo "No files given."
    exit 2  # Fail because this is likely a bug.
fi

# Older bash versions, like the default one on macOS, treat empty arrays
# as unbound variables and fail with `set -u`. I don't want to do
# weird stuff with arrays, so I check the behavior in a subshell and quit
# if it fails.
if ! ( set -eu && declare -a ARR && echo "${ARR[@]}" ) >/dev/null 2>&1; then
    echo "Your bash version is too old! $BASH_VERSION"
    exit 1
fi

# Pre-commit sets these variables for the --from-ref and --to-ref parameters.
# It does not check out the repository, and it's up to hooks to read Git file
# contents at different refs.
FROM_REF="${PRE_COMMIT_FROM_REF:-HEAD^}"
TO_REF="${PRE_COMMIT_TO_REF:-HEAD}"
echo "Comparing $FROM_REF to $TO_REF"


DIR=$( mktemp -dt wandb-prek-gocognit.XXXXXX )
trap 'rm -r "$DIR"' EXIT

if ! GOCOGNIT="$( command -v gocognit )"; then
    echo "Installing gocognit..."
    echo "TIP Install gocognit globally to speed up this script:"
    echo "  go install github.com/uudashr/gocognit/cmd/gocognit@latest"

    # Build gocognit so that we can run it outside of the core/ directory.
    # We install into a temporary directory to avoid polluting the user's PATH.
    # Caching should make the install a little faster on subsequent runs.
    GOBIN="$DIR/gobin" \
        go install github.com/uudashr/gocognit/cmd/gocognit@e304e0317bef7ab5888217553be77ae89cb24ec3 # v1.3.0
    GOCOGNIT="$DIR/gobin/gocognit"
fi
echo "Using $GOCOGNIT"


# $1    - prefix to use for output lines
# $2    - ref at which to evaluate complexity
# $3... - files to evaluate
#
# Uses the gocognit $FMT, defined below, and the temporary $DIR.
function print-complexities() {
    local prefix="$1"
    local ref="$2"
    shift 2

    # Exit early if given no files.
    if [[ $# -le 0 ]]; then
        return 0
    fi

    local dir="$DIR/$prefix"
    mkdir "$dir"
    git archive "$ref" "$@" | tar -C "$dir" -xf -

    # Run gocognit in a subshell to avoid changing the working directory.
    ( cd "$dir" && "$GOCOGNIT" -f "$prefix $FMT" "$@" )
}

# Filter out files that don't exist in FROM_REF.
# For TO_REF, we assume all given files exist.
readarray -t PREEXISTING < <( git ls-tree --name-only "$FROM_REF" "$@" )

FMT='{{.Complexity}} {{.Pos.Filename}}::{{.FuncName}}'
{
    print-complexities A "$FROM_REF" "${PREEXISTING[@]}" &&
    print-complexities B "$TO_REF"   "$@"
} |
    awk -v COMPLEXITY="$MAX_COMPLEXITY" '
    BEGIN { exitcode = 0 }

    /^A / { before[$3] = $2 }
    /^B / {
        fname = $3
        c_new = $2
        if (fname in before)
            c_old = before[fname]
        else
            c_old = 0

        # Fail if complexity increased and is above the limit.
        if ( c_new > c_old && c_new > COMPLEXITY ) {
            print "  (worsened) " c_old "=>" c_new, fname
            exitcode = 1
        }

        # Say thanks if complexity was above the limit and is reduced.
        else if ( c_new < c_old && c_old > COMPLEXITY )
            print "  (improved) " c_old "=>" c_new, fname
    }

    END {
        if (exitcode != 0) {
            print "Cognitive complexity increased above " \
                COMPLEXITY \
                " in some files."
            exit exitcode
        }
    }
    '
