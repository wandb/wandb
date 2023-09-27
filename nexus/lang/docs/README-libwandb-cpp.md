# Weights and Biases C++ library

## Status

The W&B C++ library is in developer preview / alpha state.  The interfaces are
subject to change, functionality is limited and not all datapaths are thoroughly tested.

## Sample Usage

### Build

```
unzip libwandb-cpp-linux-x86_64-alpha.zip
LD_RUN_PATH="$PWD/libwandb/lib/" \
  g++ -std=c++17 libwandb/share/libwandb/examples/logging.cpp \
  -Ilibwandb/include/ -Llibwandb/lib/ -lwandb_cpp -lwandb_core
```

### Login

The C++ library defaults to using the W&B SaaS service hosted at http://wandb.ai.
To setup your apikey you can use the python client (this functionality will be added
in the future to the library).

```
pip install wandb
wandb login
```

If you want to use a local server or a different api key, you can use environment variables.
```
WANDB_BASE_URL=https://api.wandb.ai/ \
WANDB_API_KEY=your-secret-key \
./a.out
```

## Capabilties and Limitations

Only a small subset of W&B functionality is available in the alpha release.  The functionality falls into
these few categories

### Creating a W&B Run

### Logging Data to a Run

### Finishing a Run
