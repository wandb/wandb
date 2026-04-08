#!/usr/bin/env bash
# Bans GraphQL introspection.
#
# This finds any new lines in the current commit that look like they contain
# GraphQL introspection. If it finds anything, it prints ::error commands that
# GitHub can interpret to annotate the current PR and exits with code 1.
#
# See https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-commands#setting-an-error-message

set -euo pipefail

# Default values for environment variables.
ACTION="${ACTION:-unset}"
PR_REF="${PR_REF:-}"

SCRIPT="${0/%.sh/.py}"
MAGIC_WORDS="I solemnly swear I am not adding GQL introspection."

# GitHub checks out the PR's "merge" branch, which is the proposed merge commit
# on main. In this case, "HEAD^" refers to the first parent of the merge, which
# is a commit on main, so the diff shows the changes the PR would make to main.
PROBLEMS=$(
    git diff -p --unified=0 --format=tformat: HEAD^ HEAD |
    python "$SCRIPT"
)
if [[ -z "$PROBLEMS" ]]; then
    echo "All good!"
    exit 0
fi

echo "==================================================================="
echo "Found text that looks like GraphQL introspection."
echo "The SDK may not rely on GraphQL introspection because it is"
echo "turned off in some W&B server deployments, and may eventually"
echo "be turned off in SaaS."
echo
echo "If this finding is wrong, include this text in your PR description:"
echo "  $MAGIC_WORDS"
echo "==================================================================="

# Output error annotations unless there's no new commit.
case "$ACTION" in
    edited)
        echo "Not emitting new error annotations for a PR description edit."
        ;;

    *)
        echo "ACTION is '$ACTION', emitting error annotations."
        echo "$PROBLEMS"
        ;;
esac

if [[ -z "$PR_REF" ]]; then
    echo "PR_REF not set, exiting with code 1 without checking PR description."
    exit 1
fi

PR_DESC=$( gh pr view --json body --template '{{.body}}' "$PR_REF" )
if [[ "$PR_DESC" == *"$MAGIC_WORDS"* ]]; then
    echo "PR contained magic words, exiting with code 0."
    exit 0
else
    echo "PR did not contain magic words, exiting with code 1."
    exit 1
fi
