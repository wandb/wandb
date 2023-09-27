# Weights and Biases C++ library

## Status

The W&B C++ library is in developer preview / alpha state.  The interfaces are
subject to change, functionality is limited and not all datapaths are fully tested.

## Sample Usage

### Build
```
unzip libwandb-cpp-linux-x86_64-alpha.zip
LD_RUN_PATH="$PWD/libwandb/lib/" g++ -std=c++17 libwandb/share/libwandb/examples/logging.cpp -Ilibwandb/include/ -Llibwandb/lib/ -lwandb_cpp -lwandb_core
```
