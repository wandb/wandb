#!/bin/sh

STAGED_GO_FILES=$(git diff --cached --name-only | grep ".go$")

if [[ "$STAGED_GO_FILES" = "" ]]; then
  exit 0
fi

PASS=true

for FILE in $STAGED_GO_FILES
do
  goimports -w $FILE

  golint "-set_exit_status" $FILE
  if [[ $? == 1 ]]; then
    PASS=false
  fi

  go vet $FILE
  if [[ $? != 0 ]]; then
    PASS=false
  fi
done

if ! $PASS; then
  printf "COMMIT FAILED\n"
  exit 1
else
  printf "COMMIT SUCCEEDED\n"
fi

exit 0
