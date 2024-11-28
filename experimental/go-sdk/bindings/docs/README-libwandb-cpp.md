# Weights and Biases C++ library

## Status

The W&B C++ library is in developer preview / alpha state.  The interfaces are
subject to change, functionality is limited and not all datapaths are thoroughly tested.

## Sample Usage

### Build using the library

```shell
# download library
wget https://github.com/wandb/libwandb-cpp/releases/download/v0.0-alpha.1/libwandb-cpp-linux-x86_64-alpha.zip
# unpack
unzip libwandb-cpp-linux-x86_64-alpha.zip
# compile and link
LD_RUN_PATH="$PWD/libwandb/lib/" \
  g++ -std=c++17 libwandb/share/libwandb/examples/logging.cpp \
  -Ilibwandb/include/ -Llibwandb/lib/ -lwandb_cpp -lwandb_core
```

### Examples

See examples at: [wandb cpp examples](https://github.com/wandb/wandb/tree/main/core/lang/cpp/examples).

### Login

The C++ library defaults to using the W&B SaaS service hosted at http://wandb.ai.
To setup your apikey you can use the python client (this functionality will be added
in the future to the library).

```
pip install wandb
wandb login
```

If you want to use a local server or a different api key, you can use environment variables.
```shell
WANDB_BASE_URL=https://api.wandb.ai/ \
WANDB_API_KEY=your-secret-key \
./a.out
```

## Capabilities and Limitations

Only a small subset of W&B functionality is available in the alpha release.  The functionality falls into
these few categories

### Initializing a W&B Session

This is optional but it is useful if you want to create W&B Runs with different configurations (like different
users or different backend servers - this ability will be added in a future release).

The optional syntax to create a session:
```cpp
  auto wb = new wandb::Session();
```

### Creating a W&B Run

Create a run with a session:
```cpp
  auto wb = new wandb::Session();
  auto run = wb->initRun();
```

Create a run and have a session automatically created:
```cpp
  auto run = wandb::initRun();
```

Create a run and pass parameters like a configuration map:
```cpp
  wandb::Config config = {
      {"param1", 4},
      {"param2", 4.2},
      {"param3", "hello"},
  };
  auto run = wb->initRun({
      wandb::run::WithConfig(config), wandb::run::WithProject("myproject"),
      wandb::run::WithRunName("sample run name"),
      // wandb::run::WithRunID("myrunid"),
  });
```

### Logging Data to a Run

Currently supported datatypes are floats, integers, and strings.  Additional datatypes will be added in a future release.

```cpp
  wandb::History history = {
      {"val1", 3.14 + i},
      {"val2", 1.23 + i},
      {"val3", 1},
      {"val4", "data"},
  };
  run.log(history);
```

### Finishing a Run

Runs will be finished automatically when the program finishes but they can be explicitly finished:
```cpp
  run.finish();
```

## Library details

### Building library

```shell
git clone https://github.com/wandb/wandb.git
cd wandb/core/lang
./scripts/build-dist-libwandb-cpp.sh
# package is built at ./dist/
```
