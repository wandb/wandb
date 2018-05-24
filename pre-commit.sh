#!/bin/sh
#
# Git pre-commit script that runs our unit tests as needed.
#
# To install:
#   ln -s ../../pre-commit.sh .git/hooks/pre-commit

# Redirect output to stderr.
exec 1>&2

function log() {
    echo 'pre-commit:' $@
}

function dirModified() {
    # sets is_modified if files in directory $1 have been modified.
    changed_files="$(git diff --cached --name-only --diff-filter=ACM $1 | wc -l | tr -d '[:space:]')"
    if [ "$changed_files" != "0" ]; then
        is_modified=true
    else
        is_modified=false
    fi
    if [ "$is_modified" = true ]; then
        log Modifications detected in "$1"
    fi
}

# cd to root (may not need this)
ROOT_DIR="$(git rev-parse --show-toplevel)"
cd "$ROOT_DIR"

log 'Running pre-commit checks, pass --no-verify to "git commit" to'
log 'disable.'
echo

dirModified wandb
wandb_modified="$is_modified"

# Unset all the env variables that are set during git commit hooks,
# which break the tests currently.
unset GIT_DIR
unset GIT_INDEX_FILE
unset GIT_AUTHOR_DATE
unset GIT_AUTHOR_NAME
unset GIT_PREFIX
unset GIT_AUTHOR_EMAIL


if [ "$wandb_modified" = true ]; then
    log "Running wandb tests."
    pytest
    if [ $? -ne 0 ]; then
        wandb_failed=true
    fi
fi

failed=false
if [ "$wandb_failed" = true ]; then
    log "wandb tests failed."
    log "\"cd $ROOT_DIR; pytest\" to run the tests."
    failed=true
fi

if [ "$failed" = true ]; then
    exit 1
else
    log "pre-commit check success"
fi
