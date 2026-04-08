#!/usr/bin/env bash
# Tests ban-graphql-introspection.sh.
#
# Exits with code 1 if something doesn't work.

set -euo pipefail

SHELL_SCRIPT=$( realpath "${0/%-test.sh/.sh}" )
echo "Script path is $SHELL_SCRIPT"

# Create an empty git repo in a temporary directory.
TEMP_DIR=$( mktemp -d )
cd "$TEMP_DIR"
echo "Testing in $TEMP_DIR"
git init
# git commit requires name and email
git config user.name "Anonymous"
git config user.email "<>"


# Set up a test file and add GQL introspection to it.
TEST_FILE=ban-graphql-introspection.txt

# Initial content:
cat >"$TEST_FILE" <<EOF
Line 1 contains __type but is unchanged.
Line 2 contains __type but will be deleted.
EOF
git add "$TEST_FILE" && git commit -m initial

# Updated content:
cat >"$TEST_FILE" <<EOF
Line 1 contains __type but is unchanged.
Line 2 had GQL introspection that got removed.
Line 3 uses __schema, which is not allowed.
Line 4 uses __type, also not allowed.
Line 5 uses __typename, which is OK.
EOF
git add "$TEST_FILE" && git commit -m initial


# Check that the expected output is produced.
# The script exits with code 1, which we just ignore.
RESULT=$( bash "$SHELL_SCRIPT" || exit 0 )
EXPECTED="\
===================================================================
Found text that looks like GraphQL introspection.
The SDK may not rely on GraphQL introspection because it is
turned off in some W&B server deployments, and may eventually
be turned off in SaaS.

If this finding is wrong, include this text in your PR description:
  I solemnly swear I am not adding GQL introspection.
===================================================================
ACTION is 'unset', emitting error annotations.

********************************************************************************
ban-graphql-introspection.txt
********************************************************************************
-Line 2 contains __type but will be deleted.
+Line 2 had GQL introspection that got removed.
+Line 3 uses __schema, which is not allowed.
::error file=ban-graphql-introspection.txt,line=3::Potential GraphQL introspection here.
+Line 4 uses __type, also not allowed.
::error file=ban-graphql-introspection.txt,line=4::Potential GraphQL introspection here.
PR_REF not set, exiting with code 1 without checking PR description."

# Exits with code 1 if there's a diff.
diff -c1 <( echo "$EXPECTED" ) <( echo "$RESULT" )
echo "*** PASSED TEST ***"
