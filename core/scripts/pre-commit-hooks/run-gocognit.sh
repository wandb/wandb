#!/usr/bin/env bash

################################################################################
# Exits with a non-zero code if the cognitive complexity of any Go function
# increased beyond the limit in the current commit compared to HEAD^.
#
# Usage:
#   run-gocognit.sh path/to/file1.go path/to/file2.go ...
#
# For merge commits, HEAD^ is the first parent and conventionally corresponds
# to the target branch of the merge.
#
# This script requires `gocognit` to be installed.
################################################################################
set -eu -o pipefail
MAX_COMPLEXITY=15


TMPDIR=$( mktemp -dt wandb-prek-gocognit.XXXXXX )
trap "rm -r $TMPDIR" EXIT


# Install gocognit so that we can run it outside of the core/ directory.
# We install into a temporary directory to avoid polluting the user's PATH.
# Caching makes the install fast on subsequent runs.
export GOBIN="$TMPDIR/gobin"
mkdir -p GOBIN
go install github.com/uudashr/gocognit/cmd/gocognit@e304e0317bef7ab5888217553be77ae89cb24ec3 # v1.3.0
GOCOGNIT="$GOBIN/gocognit"
echo "Using $GOCOGNIT"


################################################################################
# Check out HEAD^ versions of all files into a temporary directory.
#
# We do this to run gocognit on all files at the same time, since otherwise it
# can be a bit slow. We do this with the low-level git command
#
#   git cat-file --batch -Z

function nul-delimited-refs-and-paths() {
    # The $ref is processed by git-cat-file.
    # The $file is used by save-to-tmpdir.
    for file in "$@"; do
        local ref="HEAD^:$file"
        printf '%s %s\0' "$ref" "$file"
    done
}

function save-to-tmpdir() {
    while IFS= read -rd '' header; do
        if [[ $header =~ ^EXISTS ]]; then
            local file="${header#EXISTS }"
            echo "$file"

            local path="$TMPDIR/$file"
            mkdir -p $( dirname $path )

            IFS= read -rd '' content
            printf '%s\n' "$content" > "$path"
        fi
    done
}

readarray -t PREEXISTING < <(
    nul-delimited-refs-and-paths "$@" |
        git cat-file -Z --batch='EXISTS %(rest)' |
        save-to-tmpdir
)
################################################################################


FMT='{{.Complexity}} {{.Pos.Filename}}::{{.FuncName}}'
cat \
    <( cd "$TMPDIR" && "$GOCOGNIT" -f "A $FMT" "${PREEXISTING[@]}" ) \
    <(                 "$GOCOGNIT" -f "B $FMT" "$@" ) |

    sort |

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
