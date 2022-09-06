<p align="center">
  <img src=".github/wb-logo-lightbg.png#gh-light-mode-only" width="600" alt="Weights & Biases"/>
  <img src=".github/wb-logo-darkbg.png#gh-dark-mode-only" width="600" alt="Weights & Biases"/>
</p>

# Contributing to `wandb`

We at Weights & Biases ❤️ open source and welcome contributions from the community!
This guide discusses the development workflow and the internals of the `wandb` client library.

### Table of Contents

<!--
ToC was generated with https://ecotrust-canada.github.io/markdown-toc/
Please make sure to update the ToC when you update this page!
-->

- [Development workflow](#development-workflow)
- [Setting up your development environment](#setting-up-your-development-environment)
- [Building protocol buffers](#building-protocol-buffers)
- [Linting the code](#linting-the-code)
- [Testing](#testing)
  - [Overview](#overview)
  - [Finding good test points](#finding-good-test-points)
  - [Global Pytest Fixtures](#global-pytest-fixtures)
  - [Code Coverage](#code-coverage)
  - [Test parallelism](#test-parallelism)
  - [Functional Testing](#functional-testing)
  - [Regression Testing](#regression-testing)
- [Live development](#live-development)
- [Code organization](#code-organization)
- [Library Objectives](#library-objectives)
- [Changes from production library](#changes-from-production-library)
- [Detailed walk through of a simple program](#detailed-walk-through-of-a-simple-program)
- [Documentation Generation](#documentation-generation)
- [Deprecating Features](#deprecating-features)
- [Adding URLs](#adding-urls)

## Development workflow

1.  Browse the existing [Issues](https://github.com/wandb/client/issues) on GitHub to see
    if the feature/bug you are willing to add/fix has already been requested/reported.

    - If not, please create a [new issue](https://github.com/wandb/client/issues/new/choose).
      This will help the project keep track of feature requests and bug reports and make sure
      effort is not duplicated.

2.  If you are a first-time contributor, please go to
    [`https://github.com/wandb/client`](https://github.com/wandb/client)
    and click the "Fork" button in the top-right corner of the page.
    This will create your personal copy of the repository that you will use for development.

    - Set up [SSH authentication with GitHub](https://docs.github.com/en/authentication/connecting-to-github-with-ssh).
    - Clone the forked project to your machine and add the upstream repository
      that will point to the main `wandb` project:

      ```shell
      git clone https://github.com/<your-username>/client.git
      cd client
      git remote add upstream https://github.com/wandb/client.git
      ```

3.  Develop you contribution.
    - Make sure your fork is in sync with the main repository:
    ```shell
    git checkout master
    git pull upstream master
    ```
    - Create a `git` branch where you will develop your contribution.
      Use a sensible name for the branch, for example:
    ```shell
    git checkout -b new-awesome-feature
    ```
    - Hack! As you make progress, commit your changes locally, e.g.:
    ```shell
    git add changed-file.py tests/test-changed-file.py
    git commit -m "Added integration with a new library"
    ```
    - [Test](#testing) and [lint](#linting-the-code) your code! Please see below for a detailed discussion.
4.  Proposed changes are contributed through  
    [GitHub Pull Requests](https://help.github.com/en/github/collaborating-with-issues-and-pull-requests/about-pull-requests).

    - When your contribution is ready and the tests all pass, push your branch to GitHub:

      ```shell
      git push origin new-awesome-feature
      ```

    - Once the branch is uploaded, `GitHub` will print a URL for submitting your contribution as a pull request.
      Open that URL in your browser, write an informative title and a detailed description for your pull request,
      and submit it.
    - Please link the relevant issue (either the existing one or the one you created) to your PR.
      See the right column on the PR page.
      Alternatively, in the PR description, mention that it "Fixes _link-to-the-issue_" -
      GitHub will do the linking automatically.
    - The team will review your contribution and provide feedback.
      To incorporate changes recommended by the reviewers, commit edits to your branch,
      and push to the branch again (there is no need to re-create the pull request,
      it will automatically track modifications to your branch), e.g.:

      ```shell
      git add tests/test-changed-file.py
      git commit -m "Added another test case to address reviewer feedback"
      git push origin new-awesome-feature
      ```

    - Once your pull request is approved by the reviewers, it will be merged into the main codebase.

## Setting up your development environment

We test the library code against multiple `python` versions
and use [`pyenv`](https://github.com/pyenv/pyenv) to manage those. Install `pyenv` by running

```shell
curl -L https://github.com/pyenv/pyenv-installer/raw/master/bin/pyenv-installer | bash
```

To load `pyenv` automatically, add the following lines to your shell's startup script,
such as `~/.bashrc` or `~/.zshrc`
(and then either restart the shell, run `exec $SHELL`, or `source` the changed script):

```shell
export PYENV_ROOT="$HOME/.pyenv"
export PATH="$HOME/.pyenv/bin:$PATH"
eval "$(pyenv init --path)"
eval "$(pyenv virtualenv-init -)"
```

Then run the following command to set up your environment:

```shell
./tools/setup_dev_environment.py
```

At the first invocation, this tool will set up multiple python environments, which takes some time.
You can set up a subset of the target environments to test against, for example:

```shell
./tools/setup_dev_environment.py --python-versions 3.7 3.8
```

The tool will also set up [`tox`](https://github.com/tox-dev/tox), which we use
for automating development tasks such as code linting and testing.

Note: to switch the default python version, edit the `.python-version` file in the repository root.

### Mac with the Apple M1 chip

- The `tensorflow-macos` package that is installed on Macs with the Apple M1 chip, requires
the `h5py` package to be installed, which in turn requires `hdf5` to be installed in the system.
You can install `hdf5` and `h5py` into a `pyenv` environment with the following commands 
using [homebrew](https://brew.sh/):

```shell
$ brew install hdf5
$ export HDF5_DIR="$(brew --prefix hdf5)"
$ pip install --no-binary=h5py h5py
```

- The `soundfile` package requires the `libsndfile` package to be installed in the system.
Note that a pre-release version of `soundfile` will be installed.
You can install `libsndfile` with the following command using [homebrew](https://brew.sh/):

```shell
$ brew install libsndfile
```

- The `moviepy` package requires the `ffmpeg` package to be installed in the system.
You can install `ffmpeg` with the following command using [homebrew](https://brew.sh/):

```shell
$ brew install ffmpeg
```

- The `lightgbm` package might require build packages `cmake` and `libomp` to be installed.
You can install `cmake` and `libomp` with the following command using [homebrew](https://brew.sh/):

```shell
$ brew install cmake libomp
```

## Code organization

```bash
wandb/
├── ...
├── apis/   # Public api (still has internal api but this should be moved to wandb/internal)
│   ├── ...
│   ├── internal.py
│   ├── ...
│   └── public.py
├── cli/    # Handlers for command line functionality
├── ...
├── integration/    # Third party integration
│   ├── fastai/
│   ├── gym/
│   ├── keras/
│   ├── lightgbm/
│   ├── metaflow/
│   ├── prodigy/
│   ├── sacred/
│   ├── sagemaker/
│   ├── sb3/
│   ├── tensorboard/
│   ├── tensorflow/
│   ├── torch/
│   ├── xgboost/
│   └── ...
├── ...
├── proto/  # Protocol buffers for inter-process communication and persist file store
├── ...
├── sdk/    # User accessed functions [wandb.init()] and objects [WandbRun, WandbConfig, WandbSummary, WandbSettings]
│   ├── backend/    # Support to launch internal process
│   ├── ...
│   ├── interface/  # Interface to backend execution
│   ├── internal/   # Backend threads/processes
│   └── ...
├── ...
├── sweeps/ # Hyperparameter sweep engine (see repo: https://github.com/wandb/sweeps)
└── ...
```

## Building protocol buffers

We use [protocol buffers](https://developers.google.com/protocol-buffers) to communicate
from the user process to the `wandb` backend process.

If you update any of the `.proto` files in `wandb/proto`, you'll need to run:

```shell
make proto
```

## Linting the code

We use [`black`](https://black.readthedocs.io/), [`flake8`](https://flake8.pycqa.org/),
and [`mypy`](http://mypy-lang.org/) for code formatting and checks (including static type checks).

To reformat the code, run:

```shell
tox -e format
```

To run checks, execute:

```shell
tox -e flake8,mypy
```

## Testing

We use the [`pytest`](https://docs.pytest.org/) framework. Tests can be found in `tests/`.

By default, tests are run in parallel with 4 processes. This can be changed by setting the
`CI_PYTEST_PARALLEL` environment variable to a different value.

To run specific tests in a specific environment:

```shell
tox -e py37 -- tests/test_public_api.py -k substring_of_test
```

To run all tests in a specific environment:

```shell
tox -e py38
```

If you make changes to `requirements_dev.txt` that are used by tests, you need to recreate the python environments with:

```shell
tox -e py37 --recreate
```

Sometimes, `pytest` will swallow or shorten important print messages or stack traces sent to stdout and stderr (particularly when they are coming from background processes).
This will manifest as a test failure with no/shortened associated output.
In these cases, add the `-vvvv --showlocals` flags to stop pytest from capturing the messages and allow them to be printed to the console. Eg:

```shell
tox -e py37 -- tests/test_public_api.py -k substring_of_test -vvvv --showlocals
```

If a test fails, you can use the `--pdb -n0` flags to get the
[pdb](https://docs.python.org/3/library/pdb.html) debugger attached to the test:

```shell
tox -e py37 -- tests/test_public_api.py -k failing_test -vvvv --showlocals --pdb -n0
```

You can also manually set breakpoints in the test code (`breakpoint()`)
to inspect the test failures.

### Overview

Testing `wandb` is tricky for a few reasons:

1. `wandb.init` launches a separate process, this adds overhead and makes it difficult to assert logic happening in the backend process.
2. The library makes lots of requests to a W&B server as well as other services. We don't want to make requests to an actual server, so we need to mock one out.
3. The library has many integrations with 3rd party libraries and frameworks. We need to assert we never break compatibility with these libraries as they evolve.
4. wandb writes files to the local file system. When we're testing we need to make sure each test is isolated.
5. wandb reads configuration state from global directories such as `~/.netrc` and `~/.config/wandb/settings` we need to override these in tests.
6. The library needs to support jupyter notebook environments as well.

To make our lives easier we've created lots of tooling to help with the above challenges. Most of this tooling comes in the form of [Pytest Fixtures](https://docs.pytest.org/en/stable/fixture.html). There are detailed descriptions of our fixtures in the section below. What follows is a general overview of writing good tests for wandb.

To test functionality in the user process the `wandb_init_run` is the simplest fixture to start with. This is like calling `wandb.init()` except we don't actually launch the wandb backend process and instead returned a mocked object you can make assertions with. For example:

```python
def test_basic_log(wandb_init_run):
    wandb.log({"test": 1})
    assert wandb.run._backend.history[0]["test"] == 1
```

One of the most powerful fixtures is `live_mock_server`. When running tests we start a Flask server that provides our graphql, filestream, and additional web service endpoints with sane defaults. This allows us to use wandb just like we would in the real world. It also means we can assert various requests were made. All server logic can be found in `tests/utils/mock_server.py` and it's really straight forward to add additional logic to this server. Here's a basic example of using the `live_mock_server`:

```python
def test_live_log(live_mock_server, test_settings):
    run = wandb.init(settings=test_settings)
    run.log({"test": 1})
    ctx = live_mock_server.get_ctx()
    first_stream_hist = utils.first_filestream(ctx)["files"]["wandb-history.jsonl"]
    assert json.loads(first_stream_hist["content"][0])["test"] == 1
```

Notice we also used the `test_settings` fixture. This turns off console logging and ensures the run is automatically finished when the test finishes. Another really cool benefit of this fixture is it creates a run directory for the test at `tests/logs/NAME_OF_TEST`. This is super useful for debugging because the logs are stored there. In addition to getting the debug logs you can find the `live_mock_server` logs at `tests/logs/live_mock_server.log`.

We also have pytest fixtures that are automatically used. These include `local_netrc` and `local_settings` this ensures we never read those settings files from your own environment.

The final fixture worth noting is `notebook`. This actually runs a jupyter notebook kernel and allows you to execute specific cells within the notebook environment:

```python
def test_one_cell(notebook):
    with notebook("one_cell.ipynb") as nb:
        nb.execute_all()
        output = nb.cell_output(0)
        assert "lovely-dawn-32" in output[-1]["data"]["text/html"]
```

### Finding good test points

The wandb system can be viewed as 3 distinct services:

1. The user process where `wandb.init()` is called
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
- `test_settings` - returns a `wandb.Settings` object that can be used to initialize runs against the `live_mock_server`. See `tests/wandb_integration_test.py`
- `runner` — exposes a click.CliRunner object which can be used by calling `.isolated_filesystem()`. This also mocks out calls for login returning a dummy api key.
- `mocked_run` - returns a mocked out run object that replaces the backend interface with a MagicMock so no actual api calls are made.
- `mocked_module` - if you need to test code that calls `wandb.util.get_module("XXX")`, you can use this fixture to get a MagicMock(). See `tests/test_notebook.py`
- `wandb_init_run` - returns a fully functioning run with a mocked out interface (the result of calling `wandb.init`). No api's are actually called, but you can access what apis were called via `run._backend.{summary,history,files}`. See `test/utils/mock_backend.py` and `tests/frameworks/test_keras.py`
- `mock_server` - mocks all calls to the `requests` module with sane defaults. You can customize `tests/utils/mock_server.py` to use context or add api calls.
- `live_mock_server` - we start a live flask server when tests start. live_mock_server configures WANDB_BASE_URL point to this server. You can alter or get its context with the `get_ctx` and `set_ctx` methods. See `tests/wandb_integration_test.py`. NOTE: this currently doesn't support concurrent requests so if we run tests in parallel we need to solve for this.
- `git_repo` — places the test context into an isolated git repository
- `test_dir` - places the test into `tests/logs/NAME_OF_TEST` this is useful for looking at debug logs. This is used by `test_settings`
- `notebook` — gives you a context manager for reading a notebook providing `execute_cell`. See `tests/utils/notebook_client.py` and `tests/test_notebooks.py`. This uses `live_mock_server` to enable actual api calls in a notebook context.
- `mocked_ipython` - to get credit for codecov you may need to pretend you're in a jupyter notebook when you aren't, this fixture enables that.

### Code Coverage

We use codecov to ensure we're executing all branches of logic in our tests. Below are some JHR Protips™

1. If you want to see the lines not covered you click on the “Diff” tab. then look for any “+” lines that have a red block for the line number
2. If you want more context about the files, go to the “Files” tab, it will highlight diffs, but you have to do even more searching for the lines you might care about
3. If you don't want to use codecov, you can use local coverage (I tend to do this for speeding things up a bit, run your tests then run tox -e cover ). This will give you the old school text output of missing lines (but not based on a diff from master)

We currently have 8 categories of test coverage:

1. `project`: main coverage numbers, I don't think it can drop by more than a few percent, or you will get a failure
2. `patch/tests`: must be 100%, if you are writing code for tests, it needs to be executed, if you are planning for the future, comment out your lines
3. `patch/tests-utils`: tests/conftest.py and supporting fixtures at tests/utils/, no coverage requirements
4. `patch/sdk`: anything that matches `wandb/sdk/*.py` (so top level sdk files). These have lots of ways to test, so it should be high coverage. Currently, target is ~80% (but it is dynamic)
5. `patch/sdk-internal`: should be covered very high target is around 80% (also dynamic)
6. `patch/sdk-other`: will be a "catch all" for other stuff in `wandb/sdk/` target around 75% (dynamic)
7. `patch/apis`: we have no good fixtures for this, so until we do, this will get a waiver
8. `patch/other`: everything else, we have lots of stuff that isn't easy to test, so it is in this category, currently the requirement is ~60%

### Test parallelism

The circleci uses pytest-split to balance unittest load on multiple nodes. In order to do this efficiently every once in a while the test timing file (`.test_durations`) needs to be updated with:

```shell
CI_PYTEST_SPLIT_ARGS="--store-durations" tox -e py37
```

### Functional Testing

TODO: overview of how to write and run functional tests with [yea](https://github.com/wandb/yea)
and the [yea-wandb](https://github.com/wandb/yea-wandb) plugin.

The `yea-wandb` plugin for `yea` uses copies of several components from `tests/utils`
(`artifact_emu.py`, `mock_requests.py`, and `mock_server.py`)
to provide a test environment for functional tests. Currently, we maintain a copy of those components in
`yea-wandb/src/yea_wandb`, so they need to be in sync.

If you update one of those files, you need to:

- While working on your contribution:
  - Make a new branch (say, `shiny-new-branch`) in `yea-wandb` and pull in the new versions of the files.
    Make sure to update the `yea-wandb` version.
  - Point the client branch you are working on to this `yea-wandb` branch.
    In `tox.ini`, search for `yea-wandb==<version>` and change it to
    `https://github.com/wandb/yea-wandb/archive/shiny-new-branch.zip`.
- Once you are happy with your changes:
  - Bump to a new version by first running `make bumpversion-to-dev`, committing, and then running `make bumpversion-from-dev`. 
  - Merge and release `yea-wandb` (with `make release`).
  - If you have changes made to any file in (`artifact_emu.py`, `mock_requests.py`, or `mock_server.py`), create a new client PR to copy/paste those changes over to the corresponding file(s) in `tests/utils`. We have a Github Action that verifies that these files are equal (between the client and yea-wandb). **If you have changes in these files and you do not sync them to the client, all client PRs will fail this Github Action.** 
  - Point the client branch you are working on to the fresh release of `yea-wandb`.


### Regression Testing

<!-- TODO(jhr): describe how regression works, how to run them, where they're located etc. -->

You can find all the logic in the `wandb-testing` [repo](https://github.com/wandb/wandb-testing). The main script (`wandb-testing/regression/regression.py`) to run your regression tests can be found [here](https://github.com/wandb/wandb-testing/blob/master/regression/regression.py). Also, the main configuration file (`wandb-testing/regression/regression-config.yaml`), can be found [here](https://github.com/wandb/wandb-testing/blob/master/regression/regression-config.yaml).

#### Example usage:

```bash
git clone git@github.com:wandb/wandb-testing.git

cd wandb-testing/regression && python regression.py tests/main/huggingface/ --dryrun
```

The above script will print all of the `huggingface-transformers` test configurations.
The expected output should look something like this:

```
########################################
# huggingface-transformers init py37-pt
########################################
########################################
# huggingface-transformers init py37-pt1.4
########################################
########################################
# huggingface-transformers init py37-ptn
########################################

------------------

Good runs:
Failed runs:
```

In the names of the tests you can see the configurations of the tests:

- `init` is the configuration specified in the test [config file](https://github.com/wandb/wandb-testing/blob/master/regression/tests/main/huggingface/regression.yaml#L49).

Some details include:

- All the tests are using `py37`: [python-3.7](https://github.com/wandb/wandb-testing/blob/master/regression/regression-config.yaml#L25).
- Each test uses a different version `PyTorch`:
  - `pt`: [Latests PyTorch release](https://github.com/wandb/wandb-testing/blob/master/regression/regression-config.yaml#L54)
  - `pt1.4`: [Version 1.4 of PyTorch](https://github.com/wandb/wandb-testing/blob/master/regression/regression-config.yaml#L60)
  - `ptn`: [Nightly version of Pytorch](https://github.com/wandb/wandb-testing/blob/master/regression/regression-config.yaml#L73)

For more details about general usage and how to add new tests see this [README](https://github.com/wandb/wandb-testing/tree/master/regression#readme).

## Live development

You can enter any of the tox environments and install a live dev build with:

```shell
source .tox/py37/bin/activate
pip install -e .
```

There's also a tox dev environment using Python 3, more info [here](https://tox.readthedocs.io/en/latest/example/devenv.html).

TODO: There are lots of cool things we could do with this, currently it just puts us in iPython.

```shell
tox -e dev
```

## Library Objectives

### Supported user interface

All objects and methods that users are intended to interact with are in the `wandb/sdk` directory. Any
method on an object that is not prefixed with an underscore is part of the supported interface and should
be documented.

User interface should be typed using python 3.6+ type annotations. Older versions will use untyped interface.

### Arguments/environment variables impacting wandb functions are merged with Settings

`wandb.Settings` is the main settings object that is passed explicitly or implicitly to all `wandb` functions.

The primary objective of the design principle is that behavior of code can be impacted by multiple sources.
These sources need to be merged consistently and information given to the user when settings are overwritten
to inform the user. Examples of sources of settings:

- Enforced settings from organization, team, user, project
- Settings set by environment variables prefixed with `WANDB_`, e.g. `WANDB_PROJECT=`
- Settings passed to the `wandb.init` function: `wandb.init(project=)`
- Default settings from organization, team, project
- Settings in global settings file: `~/.config/wandb/settings`
- Settings in local settings file: `./wandb/settings`

Source priorities are defined in `wandb.sdk.wandb_settings.Source`.
Each individual setting of the Settings object is either a default or priority setting.
In the latter case, reverse priority is used to determine the source of the setting.

#### wandb.Settings internals

Under the hood in `wandb.Settings`, individual settings are represented as `wandb.sdk.wandb_settings.Property` objects
that:

- Encapsulate the logic of how to preprocess and validate values of settings throughout the lifetime of a class instance.
- Allows for runtime modification of settings with hooks, e.g. in the case when a setting depends on another setting.
- Use the `update()` method to update the value of a setting. Source priority logic is enforced when updating values.
- Determine the source priority using the `is_policy` attribute when updating the property value. E.g. if `is_policy` is
  `True`, the smallest `Source` value takes precedence.
- Have the ability to freeze/unfreeze.

Here's a basic example (for more examples, see `tests/wandb_settings_test.py`)

```python
from wandb.sdk.wandb_settings import Property, Source


def uses_https(x):
    if not x.startswith("https"):
        raise ValueError("Must use https")
    return True

base_url = Property(
    name="base_url",
    value="https://wandb.com/",
    preprocessor=lambda x: x.rstrip("/"),
    validator=[lambda x: isinstance(x, str), uses_https],
    source=Source.BASE,
)

endpoint = Property(
    name="endpoint",
    value="site",
    validator=lambda x: isinstance(x, str),
    hook=lambda x: "/".join([base_url.value, x]),
    source=Source.BASE,
)
```

```python
>>> print(base_url)  # note the stripped "/"
'https://wandb.com'
>>> print(endpoint)  # note the runtime hook
'https://wandb.com/site'
>>> print(endpoint._value)  # raw value
'site'
>>> base_url.update(value="https://wandb.ai/", source=Source.INIT)
>>> print(endpoint)  # valid update with a higher priority source
'https://wandb.ai/site'
>>> base_url.update(value="http://wandb.ai/")  # invalid value - second validator will raise exception
ValueError: Must use https
>>> base_url.update(value="https://wandb.dev", source=Source.USER)
>>> print(endpoint)  # valid value from a lower priority source has no effect
'https://wandb.ai/site'
```

The `Settings` object:

- The code is supposed to be self-documented -- see `wandb/sdk/wandb_settings.py` :)
- Uses `Property` objects to represent configurable settings.
- Clearly and compactly defines all individual settings, their default values, preprocessors, validators,
  and runtime hooks as well as whether they are treated as policies.
  - To leverage both static and runtime validation, the `validator` attribute is a list of functions
    (or a single function) that are applied in order. The first function is automatically generated
    from type annotations of class attributes.
- Provides a mechanism to update settings specifying the source (which abides the corresponding Property source logic)
  via `Settings.update()`. Direct attribute assignment is not allowed.
- Careful Settings object copying.
- Mapping interface.
- Exposes `attribute.value` if attribute is a `Property`.
- Has ability to freeze/unfreeze the object.
- `Settings.make_static()` method that we can use to replace `StaticSettings`.
- Adapted/reworked convenience methods to apply settings originating from different source.

#### Adding a new setting

- Add a new type-annotated `Settings` class attribute.
- If the setting comes with a default value/preprocessor/additional validators/runtime hooks, add them to
  the template dictionary that the `Settings._default_props` method returns, using the same key name as
  the corresponding class variable.
  - For any setting that is only computed (from other settings) and need/should not be set/updated
    (and so does not require any validation etc.), define a hook (which does not have to depend on the setting's value)
    and use `"auto_hook": True` in the template dictionary (see e.g. the `wandb_dir` setting).
- Add tests for the new setting to `tests/wandb_settings_test.py`.

### Data to be synced to server is fully validated

Calls to `wandb.log()` result in the dictionary being serialized into a schema'ed data structure.
Any non supported element should result in an immediate exception.

### All changes to objects are reflected in sync data

When changing properties of objects, those objects should serialize the changes into a schema'ed data
structure. There should be no need for `.save()` methods on objects.

### Library can be disabled

When running in disabled mode, all objects act as in memory stores of attribute information, but they do
not perform any serialization to sync data.

## Detailed walk through of a simple program

### Program

```python
1 import wandb
2 run = wandb.init(config=dict(param1=1))
3 run.config.param2 = 2
4 run.log(dict(this=3))
```

#### import wandb [line 1]

- minimal code should be run on import

#### wandb.init(...) [line 2]

- User Process:

  - Calls internal `wandb.setup()` in case the user has not yet initialized the global wandb state.
    `wandb.setup()` is similar to `wandb.init()` but it impacts the entire process or session.
    This allows multiple `wandb.init()` calls to share some common setup.
  - Sets up notification and request queues for communicating with internal process
  - Spawns internal process used for syncing passing queues and the settings object
  - Creates a Run object `RunManaged`
  - Encodes passed config dictionary into `RunManaged` object
  - Sends synchronous protocol buffer request message `RunData` to internal process
  - Wait for response for configurable amount of time. Populate run object with response data
  - Terminal (`sys.stdout`, `sys.stderr`) is wrapped which sends output to internal process with `RunOutput` message
  - Sets a global `Run` object for users who use `wandb.log()` syntax
  - `Run.on_start()` is called to display initial information about the run
  - Returns `Run` object

- Internal Process:
  - Process initialization
  - Wait on notify queue for work
  - When RunData message is seen, queue this message to be written to disk `wandb_write` and sent to cloud `wandb_send`
  - wandb_send thread sends upsert_run graphql http request
  - response is populated into a response message
  - Spin up internal threads which monitor system metrics
  - Queue response message to the user process context

#### run.config attribute setter [line 3]

- User Process:

  - Callback on the `Run` object is called with the changed config item
  - `Run` object callback generates `ConfigData` message and asynchronously sends to internal process

- Internal Process:
  - When `ConfigData` message is seen, queue message to `wandb_write` and `wandb_send`
  - `wandb_send` thread sends `upsert_run` graphql http request

#### wandb.log(...) [line 4]

- User process:

  - Log dictionary is serialized and sent asynchronously as HistoryData message to internal process

- Internal Process:
  - When `HistoryData` message is seen, queue message to `wandb_write` and `wandb_send`
  - `wandb_send` thread sends `file_stream` data to cloud server

#### end of program or wandb.finish()

- User process:
  - Terminal wrapper is shutdown and flushed to internal process
  - Exit code of program is captured and sent synchronously to internal process as `ExitData`
  - `Run.on_final()` is called to display final information about the run

## Documentation Generation

The documentation generator is broken into two parts:

- `generate.py`: Generic documentation generator for wandb/ref
- `docgen_cli.py`: Documentation generator for wandb CLI

### `generate.py`

The following is a road map of how to generate documentation for the reference.
**Steps**

1. `pip install git+https://github.com/wandb/tf-docs@wandb-docs` This installs a modified fork of [Tensorflow docs](https://github.com/tensorflow/docs). The modifications are minor templating changes.
2. `python generate.py` creates the documentation.

**Outputs**
A folder named `library` in the same folder as the code. The files in the `library` folder are the generated markdown.

**Requirements**

- wandb

### `docgen_cli.py`

**Usage**

```shell
python docgen_cli.py
```

**Outputs**
A file named `cli.md` in the same folder as the code. The file is the generated markdown for the CLI.

**Requirements**

- python >= 3.8
- wandb

## Deprecating features

Starting with version 1.0.0, `wandb` will be using [Semantic Versioning](https://semver.org/).
The major version of the library will be incremented for all backwards-incompatible changes,
including dropping support for older Python versions.

Features currently marked as deprecated will be removed in the next major version (1.0.0).

<!--
It is safe to depend on `wandb` like this: `wandb >=x.y, <(x+1)`,
where `x.y` is the first version that includes all features you need.
-->

### Marking a feature as deprecated

To mark a feature as deprecated (and to be removed in the next major release), please follow these steps:

- Add a new field to the `Deprecated` message definition in `wandb/proto/wandb_telemetry.proto`,
  which will be used to track the to-be-deprecated feature usage.
- Rebuild protocol buffers and re-generate `wandb/proto/wandb_deprecated.py` by running `make proto`.
- Finally, to mark a feature as deprecated, call `wand.sdk.lib.deprecate` in your code:

```python
from wandb.sdk.lib import deprecate

deprecate.deprecate(
    field_name=deprecate.Deprecated.<new_field_name>,  # new_field_name from step 1
    warning_message="This feature is deprecated and will be removed in a future release.",
)
```

## Adding URLs

All URLs displayed to the user should be added to `wandb/sdk/lib/wburls.py`.  This will better
ensure that URLs do not lead to broken links.

Once you add the URL to that file you will need to run:
```shell
python tools/generate-tool.py --generate
```
