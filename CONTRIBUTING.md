# Wandb library


## Get the code / library

Checkout from github:
```
git clone --recurse-submodules git@github.com:wandb/client.git
cd client
pip install -e .
```

Install from pip:
```
pip install --upgrade git+git://github.com/wandb/client.git
```

Or from pypi:
```
pip install --upgrade wandb
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
wandb/sweeps_engine        - Hyperparameter sweep engine (pin of https://github.com/wandb/sweeps)
wandb/integration/keras    - keras integration
wandb/integration/pytorch  - pytorch integration
```

The hyperparameter engine `wandb/sweeps_engine` is a submodule: https://github.com/wandb/sweeps.

To check out the currently pinned version of the sweeps submodule, do:

```
make submodule-update
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

Sometimes pytest will swallow important print messages or stacktraces sent to stdout and stderr (particularly when they are coming from background processes). This will manifest as a test failure with no associated output. In these cases, add the `-s` flag to stop pytest from capturing the messages and allow them to be printed to the console. Eg:

```shell
tox -e py37 -- tests/test_public_api.py -k substring_of_test -s
```

If you make changes to `requirements_dev.txt` that are used by tests, you need to recreate the python environments with:

```shell
tox -e py37 --recreate
```

### Overview

Testing wandb is tricky for a few reasons:

1. `wandb.init` launches a separate process, this adds overhead and makes it difficult to assert logic happening in the backend process.
2. The library makes lot's of requests to a W&B server as well as other services.  We don't want to make requests to an actual server so we need to mock one out.
3. The library has many integrations with 3rd party libraries and frameworks.  We need to assert we never break compatibility with these libraries as they evolve.
4. wandb writes files to the local file system.  When we're testing we need to make sure each test is isolated.
5. wandb reads configuration state from global directories such as `~/.netrc` and `~/.config/wandb/settings` we need to override these in tests.
6. The library needs to support jupyter notebook environments as well.

To make our lives easier we've created lots tooling to help with the above challenges.  Most of this tooling comes in the form of [Pytest Fixtures](https://docs.pytest.org/en/stable/fixture.html).  There are detailed descriptions of our fixtures in the section below.  What follows is a general overview of writing good tests for wandb.

To test functionality in the user process the `wandb_init_run` is the simplest fixture to start with.  This is like calling `wandb.init()` except we don't actually launch the wandb backend process and instead returned a mocked object you can make assertions with.  For example:

```python
def test_basic_log(wandb_init_run):
    wandb.log({"test": 1})
    assert wandb.run._backend.history[0]["test"] == 1
```

One of the most powerful fixtures is `live_mock_server`.  When running tests we start a Flask server that provides our graphql, filestream, and additional web service endpoints with sane defaults.  This allows us to use wandb just like we would in the real world.  It also means we can assert various requests were made.  All server logic can be found in `tests/utils/mock_server.py` and it's really straight forward to add additional logic to this server.  Here's a basic example of using the live_mock_server:

```python
def test_live_log(live_mock_server, test_settings):
    run = wandb.init(settings=test_settings)
    run.log({"test": 1})
    ctx = live_mock_server.get_ctx()
    first_stream_hist = utils.first_filestream(ctx)["files"]["wandb-history.jsonl"]
    assert json.loads(first_stream_hist["content"][0])["test"] == 1
```

Notice we also used the `test_settings` fixture.  This turns off console logging and ensures the run is automatically finished when the test finishes.  Another really cool benefit of this fixture is it creates a run directory for the test at `tests/logs/NAME_OF_TEST`.  This is super useful for debugging because the logs are stored there. In addition to getting the debug logs you can find the live_mock_server logs at `tests/logs/live_mock_server.log`.

We also have pytest fixtures that are automatically used.  These include `local_netrc` and `local_settings` this ensures we never read those settings files from your own environment.

The final fixture worth noting is `notebook`.  This actually runs a jupyter notebook kernel and allows you to execute specific cells within the notebook environment:

```python
def test_one_cell(notebook):
    with notebook("one_cell.ipynb") as nb:
        nb.execute_all()
        output = nb.cell_output(0)
        assert "lovely-dawn-32" in output[-1]["data"]["text/html"]
```

### Finding good test points

The wandb system can be viewed as 3 distinct services:
1. The user process where wandb.init() is called
2. The internal process where work is done to format data to be synced to the server
3. The backend server which listens to graphql endpoints and populates a database

The interfaces are described here:

```
  Users   .  Shared  .  Internal .  Mock
  Process .  Queues  .  Process  .  Server
          .          .           .
  +----+  .  +----+  .  +----+   .  +----+
  | Up |  .  | Sq |  .  | Ip |   .  | Ms |
  +----+  .  +----+  .  +----+   .  +----+
    |     .    |     .    |      .    |
    | ------>  | -------> | --------> |    1
    |     .    |     .    |      .    |
    |     .    | -------> | --------> |    2
    |     .    |     .    |      .    |
    | ------>  |     .    |      .    |    3
    |     .    |     .    |      .    |

1. Full codepath from wandb.init() to mock_server
   Note: coverage only counts for the User Process and interface code
   Example: tests/wandb_integration_test.py
2. Inject into the Shared Queues to mock_server
   Note: coverage only counts for the interface code and internal process code
   Example: tests/test_sender.py
3. From wandb.Run object to Shared Queues
   Note: coverage counts for User Process
   Example: tests/wandb_run_test.py
```

Good examples of tests for each level of testing can be found at:
- [test_metric_user.py](tests/test_metric_user.py): User process tests
- [test_metric_internal.py](tests/test_metric_internal.py): Internal process tests
- [test_metric_full.py](tests/test_metric_full.py): Full stack tests

### Global Pytest Fixtures

All global fixtures are defined in `tests/conftest.py`:

- `local_netrc` - used automatically for all tests and patches the netrc logic to avoid interacting with your system .netrc
- `local_settings` - used automatically for all tests and patches the global settings path to an isolated directory.
- `test_settings` - returns a `wandb.Settings` object that can be used to initialize runs against the `live_mock_server`.  See `tests/wandb_integration_test.py`
- `runner` — exposes a click.CliRunner object which can be used by calling `.isolated_filesystem()`.  This also mocks out calls for login returning a dummy api key.
- `mocked_run` - returns a mocked out run object that replaces the backend interface with a MagicMock so no actual api calls are made.
- `mocked_module` - if you need to test code that calls `wandb.util.get_module("XXX")`, you can use this fixture to get a MagicMock().  See `tests/test_notebook.py`
- `wandb_init_run` - returns a fully functioning run with a mocked out interface (the result of calling wandb.init).  No api's are actually called, but you can access what apis were called via `run._backend.{summary,history,files}`.  See `test/utils/mock_backend.py` and `tests/frameworks/test_keras.py`
- `mock_server` - mocks all calls to the `requests` module with sane defaults.  You can customize `tests/utils/mock_server.py` to use context or add api calls.
- `live_mock_server` - we start a live flask server when tests start.  live_mock_server configures WANDB_BASE_URL point to this server.  You can alter or get it's context with the `get_ctx` and `set_ctx` methods.  See `tests/wandb_integration_test.py`.  NOTE: this currently doesn't support concurrent requests so if we run tests in parallel we need to solve for this.
- `git_repo` — places the test context into an isolated git repository
- `test_dir` - places the test into `tests/logs/NAME_OF_TEST` this is useful for looking at debug logs.  This is used by `test_settings`
- `notebook` — gives you a context manager for reading a notebook providing `execute_cell`.  See `tests/utils/notebook_client.py` and `tests/test_notebooks.py`.  This uses `live_mock_server` to enable actual api calls in a notebook context.
- `mocked_ipython` - to get credit for codecov you may need to pretend you're in a jupyter notebook when you aren't, this fixture enables that.

### Code Coverage

We use codecov to ensure we're executing all branches of logic in our tests.  Below are some JHR Protips™

1. If you want to see the lines not covered you click on the “Diff” tab.   then look for any “+” lines that have a red block for the line number
2. If you want more context about the files, go to the “Files” tab, it will highlight diffs but you have to do even more searching for the lines you might care about
3. If you dont want to use codecov, you can use local coverage (i tend to do this for speeding things up a bit, run your tests then run tox -e cover ).   This will give you the old school text output of missing lines (but not based on a diff from master)

We currently have 8 categories of test coverage:

1. project: main coverage numbers, i dont think it can drop by more than a few percent or you will get a failure
2. patch/tests: must be 100%, if you are writing code for tests, it needs to be executed, if you are planning for the future, comment out your lines
3. patch/tests-utils: tests/conftest.py and supporting fixtures at tests/utils/, no coverage requirements
4. patch/sdk: anything that matches `wandb/sdk/*.py` (so top level sdk files).   These have lots of ways to test, so it should be high coverage.  currently target is ~80% (but it is dynamic)
5. patch/sdk-internal: should be covered very high target is around 80% (also dynamic)
6. patch/sdk-other: will be a catch all for other stuff in wandb/sdk/ target around 75% (dynamic)
7. patch/apis: we have no good fixtures for this, so until we do, this will get a waiver
8. patch/other: everything else, we have lots of stuff that isnt easy to test, so it is in this category, currently the requirement is ~60%

### Test parallelism

The circleci uses pytest-split to balance unittest load on multiple nodes.  In order to do this efficiently every once in a while the test timing file (`.test_durations`) needs to be updated with:
```shell
CI_PYTEST_SPLIT_ARGS="--store-durations" tox -e py37
```

### Regression Testing

TODO(jhr): describe how regression works, how to run them, where they're located etc.

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
- wandb_send thread sends upsert_run graphql http request

#### wandb.log()

User process:

- Log dictionary is serialized and sent asynchronously as HistoryData message to internal process

Internal Process:

- When HistoryData message is seen, queue message to wandb_write and wandb_send
- wandb_send thread sends file_stream data to cloud server

#### end of program or wandb.finish()

User process:

- Terminal wrapper is shutdown and flushed to internal process
- Exit code of program is captured and sent synchronously to internal process as ExitData
- Run.on_final() is called to display final information about the run

## Documentation Generation

The documentation generator is broken into two parts:
- `generate.py`: Generic documentation generator for wandb/ref
- `docgen_cli.py`: Documentation generator for wandb CLI

### `generate.py`
The follwing is a road map of how to generate documentaion for the reference.
**Steps**
1. `pip install git+https://github.com/wandb/tf-docs@wandb-docs` This installs a modified fork of [Tensorflow docs](https://github.com/tensorflow/docs). The modifications are minor templating changes.
3. `python generate.py` creates the documentation.

**Outputs**
A folder named `library` in the same folder as the code. The files in the `library` folder are the generated markdown.

**Requirements**
- wandb

### `docgen_cli.py`
**Usage**
```bash
$ python docgen_cli.py
```

**Outputs**
A file named `cli.md` in the same folder as the code. The file is the generated markdown for the CLI.

**Requirements**
- python >= 3.8
- wandb
