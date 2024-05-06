#!/bin/bash
set -e

# npm install -g clang-format
find cpp/ -iname *.h -o -iname *.cpp | xargs clang-format -i
