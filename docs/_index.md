---
title: Developer Documentation
---

# Wandb library

https://paper.dropbox.com/doc/Cling-CLI-Refactor-lETNuiP0Rax8yjTi03Scp

## Get the code / library

Checkout from github:
```
git clone git@github.com:wandb/client.git
cd client
pip install -e .
```

Install from pip:
```
pip install --upgrade git+git://github.com/wandb/client.git
```

Or from pypi:
```
pip install --upgrade wandb`
```

## Code organization

```
wandb/sdk                  - User accessed functions [wandb.init()] and objects [WandbRun, WandbConfig, WandbSummary, WandbSettings]
wandb/sdk_py27             - Generated files [currently by strip.sh]
wandb/backend              - Support to launch internal process
wandb/interface            - Interface to backend execution 
wandb/proto                - Protocol buffers for inter-process communication and persist file store
wandb/internal             - Backend threads/processes
wandb/apis                 - Public api (still has internal api but this should be moved to wandb/internal)
wandb/cli                  - Handlers for command line functionality
wandb/sweeps               - sweeps stuff (mostly unmodified for now)
wandb/integration/keras    - keras integration
wandb/integration/pytorch  - pytorch integration
```

## Setup development environment

In order to run unittests please install pyenv:

```shell
curl -L https://raw.githubusercontent.com/yyuu/pyenv-installer/master/bin/pyenv-installer | bash
# put the output in your ~/.bashrc
```
```

then run:


```shell
./tools/setup_dev_environment.sh
```

## Building protocol buffers

We use protocol buffers to communicate from the user process to the wandb backend process.

If you update any of the .proto files in wandb/proto, you'll need to run:

```
make proto
```

## Code checks

 - Reformat: `tox -e format`
 - Type check: `tox -e flake8,mypy`
 - Misc: `tox`

## Testing

Tests can be found in `tests/`.  We use tox to run tests, you can run all tests with:

```shell
tox
```

You should run this before you make a commit.  To run specific tests in a specific environment:

```shell
tox -e py37 -- tests/test_public_api.py -k substring_of_test
```

If you make changes to `requirements_dev.txt` that are used by tests, you need to recreate the python environments with:

```shell
tox -e py37 --recreate
```

To debug issues with leaving files open, you can pass `--open-files` to pytest to have tests fail that leave open files:
https://github.com/astropy/pytest-openfile

```shell
tox -e py37 -- --open-files
```

### Pytest Fixtures

`tests/conftest.py` contains a number of helpful fixtures automatically exposed to all tests as arguments for testing the app:

- `local_netrc` - used automatically for all tests and patches the netrc logic to avoid interacting with your system .netrc
- `local_settings` - used automatically for all tests and patches the global settings path to an isolated directory.
- `test_settings` - returns a `wandb.Settings` object that can be used to initialize runs against the `live_mock_server`.  See `tests/wandb_integration_test.py`
- `runner` — exposes a click.CliRunner object which can be used by calling `.isolated_filesystem()`.  This also mocks out calls for login returning a dummy api key.
- `mocked_run` - returns a mocked out run object that replaces the backend interface with a MagicMock so no actual api calls are made.
- `wandb_init_run` - returns a fully functioning run with a mocked out interface (the result of calling wandb.init).  No api's are actually called, but you can access what apis were called via `run._backend.{summary,history,files}`.  See `test/utils/mock_backend.py` and `tests/frameworks/test_keras.py`
- `mock_server` - mocks all calls to the `requests` module with sane defaults.  You can customize `tests/utils/mock_server.py` to use context or add api calls.
- `live_mock_server` - we start a live flask server when tests start.  live_mock_server configures WANDB_BASE_URL point to this server.  You can alter or get it's context with the `get_ctx` and `set_ctx` methods.  See `tests/wandb_integration_test.py`.  NOTE: this currently doesn't support concurrent requests so if we run tests in parallel we need to solve for this.
- `git_repo` — places the test context into an isolated git repository
- `test_dir` - places the test into `tests/logs/NAME_OF_TEST` this is useful for looking at debug logs.  This is used by `test_settings`
- `notebook` — gives you a context manager for reading a notebook providing `execute_cell`.  See `tests/utils/notebook_client.py` and `tests/test_notebooks.py`.  This uses `live_mock_server` to enable actual api calls in a notebook context.

## Live development

You can enter any of the tox environments and install a live dev build with:

```shell
source .tox/py37/bin/activate
pip install -e .
```

There's also a tox dev environment using Python 3, more info here: https://tox.readthedocs.io/en/latest/example/devenv.html

TODO: There are lots of cool things we could do with this, currently it just puts us in iPython.

```shell
tox -e dev
```

## Library Objectives

### Supported user interface

All objects and methods that users are intended to interact with are in the wandb/sdk directory.  Any
method on an object that is not prefixed with an underscore is part of the supported interface and should
be documented.

User interface should be typed using python 3.6+ type annotations.  Older versions will use untyped interface.

### Arguments/environment variables impacting wandb functions are merged with Settings

See below for more about the Settings object.  The primary objective of this design principle is that
behavior of code can be impacted by multiple sources.  These sources need to be merged consistently
and information given to the user when settings are overwritten to inform the user.  Examples of sources
of settings:

 - Enforced settings from organization, team, user, project
 - settings set by environment variables: WANDB_PROJECT=
 - settings passed to wandb function: wandb.init(project=)
 - Default settings from organization, team, project
 - settings in global settings file: ~/.config/wandb/settings
 - settings in local settings file: ./wandb/settings

### Data to be synced to server is fully validated

Calls to wandb.log() result in the dictionary being serialized into a schema'ed data structure.
Any non supported element should result in an immediate exception.

### All changes to objects are reflected in sync data

When changing properties of objects, those objects should serialize the changes into a schema'ed data
structure.  There should be no need for .save() methods on objects.

### Library can be disabled

When running in disabled mode, all objects act as in memory stores of attribute information but they do
not perform any serialization to sync data.

## Changes from production library

### wandb.Settings

Main settings object that is passed explicitly or implicitly to all wandb functions

### wandb.setup()

Similar to wandb.init() but it impacts the entire process or session.  This allows multiple wandb.init() calls to share
some common setup.   It is not necessary as it will be called implicitly by the first wandb.init() call.


## Detailed walk through of a simple program

### Program

```
import wandb
run = wandb.init(config=dict(param1=1))
run.config.param2 = 2
run.log(dict(this=3))
```

### Steps

#### import wandb

- minimal code should be run on import

#### wandb.init()

User Process:

- Calls internal wandb.setup() in case the user has not yet initialized the global wandb state
- Sets up notification and request queues for communicating with internal process
- Spawns internal process used for syncing passing queues and the settings object
- Creates a Run object `RunManaged`
- Encodes passed config dictionary into RunManaged object
- Sends synchronous protocol buffer request message `RunData` to internal process
- Wait for response for configurable amount of time.  Populate run object with response data
- Terminal (sys.stdout, sys.stderr) is wrapped which sends output to internal process with `RunOutput` message
- Sets a global Run object for users who use wandb.log() syntax
- Run.on_start() is called to display initial information about the run
- Returns Run object

Internal Process:

- Process initialization
- Wait on notify queue for work
- When RunData message is seen, queue this message to be written to disk `wandb_write` and sent to cloud `wandb_send`
- wandb_send thread sends upsert_run graphql http request
- response is populated into a response message
- Spin up internal threads which monitor system metrics
- Queue response message to the user process context

#### run.config attribute setter

User Process:

- Callback on the Run object is called with the changed config item
- Run object callback generates ConfigData message and asynchronously sends to internal process 

Internal Process:

- When ConfigData message is seen, queue message to wandb_write and wandb_send
- wandb_send thread sends upsert_run grapql http request

#### wandb.log()

User process:

- Log dictionary is serialized and sent asynchronously as HistoryData message to internal process

Internal Process:

- When HistoryData message is seen, queue message to wandb_write and wandb_send
- wandb_send thread sends file_stream data to cloud server

#### end of program or wandb.join()

User process:

- Terminal wrapper is shutdown and flushed to internal process
- Exit code of program is captured and sent synchronously to internal process as ExitData
- Run.on_final() is called to display final information about the run
