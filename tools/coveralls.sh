#!/bin/bash
if [[ -n $(git status -s) ]]; then
  echo "ERROR: Untracked files, commit before running coveralls report."
  echo ""
  echo "Check untracked files with: git status -s"
  exit 1
fi
ENVS="yapf,mypy,"
ENVS+=`tox -a | egrep ^py[23] | paste -s -d, -` 
ENVS+=",cover,coveralls"
tox -e${ENVS}
