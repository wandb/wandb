#!/bin/sh

rm -rf ../dist/static
rm build/report.html
cp -r build/* ../dist/
echo "Release created"