#!/bin/bash
set -e

# NOTE: this is not final... just for testing

# prep location
rm -rf export/
mkdir export
mkdir export/lib
mkdir export/include
mkdir export/examples

# build nexus binary
rm -rf tmp
mkdir tmp
# build binary
cd ..
go build -o lib/tmp/nexusimage.bin cmd/nexus/main.go
cd -

# build shared-library
cp core/*.go tmp/
cd tmp/
go build -buildmode c-shared -o ../export/libwandbcore.so wandbcore.go nexusimage.go
go build -buildmode c-archive -o ../export/libwandbcore.a wandbcore.go nexusimage.go
mv ../export/libwandbcore.so ../export/libwandbcore.a ../export/lib/
mv ../export/libwandbcore.h ../export/include/
cd -
rm -rf tmp/

# build c library
mkdir tmp/
cp clib/* tmp/
cd tmp/
gcc -c -Wall -Werror -fpic -I../export/include/ -I. libwandb.c
gcc -shared -o libwandb.so libwandb.o
chmod -x libwandb.so
ar rcs libwandb.a libwandb.o
mv libwandb.so libwandb.a ../export/lib/
mv libwandb.h ../export/include/
cd -
rm -rf tmp/

# build client prog
cd examples/
LD_RUN_PATH="$PWD/../export/lib/" gcc train.c -o ../export/examples/train -I../export/include/ -L../export/lib/ -lwandb -lwandbcore
gcc train.c -o ../export/examples/train-staticlibs -I../export/include/ -L../export/lib/ -l:libwandb.a -l:libwandbcore.a
# gcc train.c -static -o ../export/examples/train-static -I../export/include/ -L../export/lib/ -l:libwandb.a -l:libwandbcore.a
