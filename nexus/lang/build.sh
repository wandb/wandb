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
rm -rf tmpbuild
mkdir tmpbuild
# build binary
cd ..
go build -o lib/tmpbuild/embed-nexus.bin cmd/nexus/main.go
cd -

# build shared-library
cp wandbcore/*.go tmpbuild/
cd tmpbuild/
go build -buildmode c-shared -o ../export/libwandbcore.so *.go
go build -buildmode c-archive -o ../export/libwandbcore.a *.go
mv ../export/libwandbcore.so ../export/libwandbcore.a ../export/lib/
mv ../export/libwandbcore.h ../export/include/
cd -
rm -rf tmpbuild/

# build c library
mkdir tmpbuild/
cp clib/* tmpbuild/
cd tmpbuild/
gcc -c -Wall -Werror -fpic -I../export/include/ -I. libwandb.c
if [ "x$(uname -o)" = "xDarwin" ]; then
    gcc -shared -undefined dynamic_lookup -o libwandb.so libwandb.o
else
    gcc -shared -o libwandb.so libwandb.o
fi
chmod -x libwandb.so
ar rcs libwandb.a libwandb.o
mv libwandb.so libwandb.a ../export/lib/
mv libwandb.h ../export/include/
cd -
rm -rf tmpbuild/

# build client prog
cd examples/
LD_RUN_PATH="$PWD/../export/lib/" gcc train.c -o ../export/examples/train -I../export/include/ -L../export/lib/ -lwandb -lwandbcore
# gcc train.c -o ../export/examples/train-staticlibs -I../export/include/ -L../export/lib/ -l:libwandb.a -l:libwandbcore.a
# gcc train.c -static -o ../export/examples/train-static -I../export/include/ -L../export/lib/ -l:libwandb.a -l:libwandbcore.a
