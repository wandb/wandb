#!/bin/bash
set -e

# NOTE: this is not final... just for testing

# prep location
rm -rf export/
mkdir export
mkdir export/lib
mkdir export/include
mkdir export/examples

# build core binary
rm -rf tmpbuild
mkdir tmpbuild
# build binary
cd ..
SYSTEM=`uname -s`
if [ "x$SYSTEM" == "xLinux" ]; then
CGO_ENABLED=1 go build \
  -ldflags "-extldflags \"-fuse-ld=gold -Wl,--weak-unresolved-symbols\"" \
  -o lang/tmpbuild/embed-core.bin cmd/core/main.go
else
go build \
  -o lang/tmpbuild/embed-core.bin cmd/core/main.go
fi
cd -

# build shared-library
cp core/*.go tmpbuild/
cd tmpbuild/
go build -tags=libwandb_core -buildmode c-shared -o ../export/libwandb_core.so *.go
go build -tags=libwandb_core -buildmode c-archive -o ../export/libwandb_core.a *.go
mv ../export/libwandb_core.so ../export/libwandb_core.a ../export/lib/
mv ../export/libwandb_core.h ../export/include/
cd -
rm -rf tmpbuild/

# build c library
mkdir tmpbuild/
cp c/lib/* tmpbuild/
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

# build cpp library
mkdir tmpbuild/
cp cpp/lib/* tmpbuild/
cd tmpbuild/
g++ -std=c++17 -c -Wall -Werror -Wno-unused-private-field -fpic -I../export/include/ -I. libwandb_cpp.cpp
if [ "x$(uname -o)" = "xDarwin" ]; then
    g++ -std=c++17 -shared -undefined dynamic_lookup -o libwandb_cpp.so libwandb_cpp.o
else
    g++ -std=c++17 -shared -o libwandb_cpp.so libwandb_cpp.o
fi
chmod -x libwandb_cpp.so
ar rcs libwandb_cpp.a libwandb_cpp.o
mv libwandb_cpp.so libwandb_cpp.a ../export/lib/
mv libwandb_cpp.h ../export/include/
cd -
rm -rf tmpbuild/

# build client prog
cd c/examples/
LD_RUN_PATH="$PWD/../../export/lib/" gcc train.c -o ../../export/examples/train -I../../export/include/ -L../../export/lib/ -lwandb -lwandb_core
# gcc train.c -o ../export/examples/train-staticlibs -I../export/include/ -L../export/lib/ -l:libwandb.a -l:libwandbcore.a
# gcc train.c -static -o ../export/examples/train-static -I../export/include/ -L../export/lib/ -l:libwandb.a -l:libwandbcore.a
cd -

# build client prog (cpp)
cd cpp/examples/
LD_RUN_PATH="$PWD/../../export/lib/" g++ -std=c++17 train.cpp -o ../../export/examples/traincpp -I../../export/include/ -L../../export/lib/ -lwandb_cpp -lwandb_core
cd -

# build client prog session (cpp)
cd cpp/examples/
LD_RUN_PATH="$PWD/../../export/lib/" g++ -std=c++17 train_session.cpp -o ../../export/examples/train_session -I../../export/include/ -L../../export/lib/ -lwandb_cpp -lwandb_core
cd -
