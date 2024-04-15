<p align="center">
  <img src="./docs/README_images/logo-dark.svg#gh-dark-mode-only" width="600" alt="Weights & Biases" />
  <img src="./docs/README_images/logo-light.svg#gh-light-mode-only" width="600" alt="Weights & Biases" />
</p>

# Contributing to `wandb`

We at Weights & Biases ❤️ open source and welcome contributions from the community!
This guide discusses the development workflow and the internals of the `wandb` library.

### Table of Contents

<!--
ToC was generated with https://ecotrust-canada.github.io/markdown-toc/
Please make sure to update the ToC when you update this page!
-->
- [Development workflow](#development-workflow)
  * [Conventional Commits](#conventional-commits)
    + [Types](#types)
    + [Scopes](#scopes)
    + [Subjects](#subjects)
- [Setting up your development environment](#setting-up-your-development-environment)
- [Linting the code](#linting-the-code)
- [Testing](#testing)
  * [Using pytest](#using-pytest)
- [Auto-Generating Code](#auto-generating-code)
  * [Building protocol buffers](#building-protocol-buffers)
  * [Arguments/environment variables impacting wandb functions are merged with Settings](#arguments-environment-variables-impacting-wandb-functions-are-merged-with-settings)
    + [wandb.Settings internals](#wandbsettings-internals)
    + [Adding a new setting](#adding-a-new-setting)
  * [Deprecating features](#deprecating-features)
    + [Marking a feature as deprecated](#marking-a-feature-as-deprecated)
  * [Adding URLs](#adding-urls)
- [Editable mode:](#editable-mode-)
  * [Adding URLs](#adding-urls)

## Development workflow

1.  Browse the existing [Issues](https://github.com/wandb/wandb/issues) on GitHub to see
    if the feature/bug you are willing to add/fix has already been requested/reported.

    - If not, please create a [new issue](https://github.com/wandb/wandb/issues/new/choose).
      This will help the project keep track of feature requests and bug reports and make sure
      effort is not duplicated.

2.  If you are a first-time contributor, please go to
    [`https://github.com/wandb/wandb`](https://github.com/wandb/wandb)
    and click the "Fork" button in the top-right corner of the page.
    This will create your personal copy of the repository that you will use for development.

    - Set up [SSH authentication with GitHub](https://docs.github.com/en/authentication/connecting-to-github-with-ssh).
    - Clone the forked project to your machine and add the upstream repository
      that will point to the main `wandb` project:

      ```shell
      git clone https://github.com/<your-username>/wandb.git
      cd wandb
      git remote add upstream https://github.com/wandb/wandb.git
      ```

3.  Develop your contribution.
    - Make sure your fork is in sync with the main repository:
    ```shell
    git checkout main
    git pull upstream main
    ```
    - Create a `git` branch where you will develop your contribution.
      Use a sensible name for the branch, for example:
    ```shell
    git checkout -b <username>/<short-dash-seperated-feature-description>
    ```
    - Hack! As you make progress, commit your changes locally, e.g.:
    ```shell
    git add changed-file.py tests/test-changed-file.py
    git commit -m "feat(integrations): Add integration with the `awesomepyml` library"
    ```
    - [Test](#testing) and [lint](#linting-the-code) your code! Please see below for a detailed discussion.
    - Ensure compliance with [conventional commits](https://www.conventionalcommits.org/en/v1.0.0/),
      see [below](#conventional-commits). This is enforced by the CI and will prevent your PR from
      being merged if not followed.
4.  Proposed changes are contributed through
    [GitHub Pull Requests](https://help.github.com/en/github/collaborating-with-issues-and-pull-requests/about-pull-requests).

    - When your contribution is ready and the tests all pass, push your branch to GitHub:

      ```shell
      git push origin <username>/<short-dash-seperated-feature-description>
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
      git commit -m "test(sdk): Add a test case to address reviewer feedback"
      git push origin <username>/<short-dash-seperated-feature-description>
      ```

    - Once your pull request is approved by the reviewers, it will be merged into the main branch in the repository.

### Conventional Commits

At Weights & Biases, we ask that all PR titles conform to the
[Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/) specification.
Conventional Commits is a lightweight convention on top of commit messages.

**Structure**

The commit message should be structured as follows:

```jsx
<type>(<scope>): <description>
```

<aside>
⭐ **TLDR:** Every commit that has type `feat` or `fix` is **user-facing**.
If notes are user-facing, please make sure users can clearly understand your commit message.

</aside>

#### Types

Only certain types are permitted.

<aside>
⭐ User-facing notes such as `fix` and `feat` should be written so that a user can clearly understand the changes.
If the feature or fix does not directly impact users, consider using a different type.
Examples can be found in the section below.

</aside>

| Type     | Name                        | Description                                                                                  | User-facing? |
|----------|-----------------------------|----------------------------------------------------------------------------------------------|--------------|
| feat     | ✨ Feature                   | A pull request that adds new functionality that directly impacts users                       | Yes          |
| fix      | 🐛 Fix                      | A pull request that fixes a bug                                                              | Yes          |
| docs     | 📚 Documentation            | Documentation changes only                                                                   | Maybe        |
| style    | 💎 Style                    | Changes that do not affect the meaning of the code (e.g. linting or adding type annotations) | No           |
| refactor | 📦 Code Refactor            | A code change that neither fixes a bug nor adds a feature                                    | No           |
| perf     | 🚀 Performance Improvements | A code change that improves performance                                                      | No           |
| test     | 🚨 Tests                    | Adding new or missing tests or correcting existing tests                                     | No           |
| build    | 🛠 Builds                   | Changes that affect the build system (e.g. protobuf) or external dependencies                | Maybe        |
| ci       | ⚙️ Continuous Integrations  | Changes to our CI configuration files and scripts                                            | No           |
| chore    | ♻️ Chores                   | Other changes that don't modify source code files.                                           | No           |
| revert   | 🗑 Reverts                  | Reverts a previous commit                                                                    | Maybe        |
| security | 🔒 Security                 | Security fix/feature                                                                         | Maybe        |

#### Scopes

Which part of the codebase does this change impact? Only certain scopes are permitted.

| Scope        | Name                     | Description                                             |
|--------------|--------------------------|---------------------------------------------------------|
| sdk          | Software Development Kit | Generic SDK changes or if can't define a narrower scope |
| cli          | Command-Line Interface   | Generic CLI changes                                     |
| public-api   | Public API               | Public API changes                                      |
| integrations | Integrations             | Changes related to third-party integrations             |
| artifacts    | Artifacts                | Changes related to Artifacts                            |
| media        | Media Types              | Changes related to Media types                          |
| sweeps       | Sweeps                   | Changes related to Sweeps                               |
| launch       | Launch                   | Changes related to Launch                               |

Sometimes a change may span multiple scopes. In this case, please choose the scope that would be most relevant to the user.


#### Subjects

Write a short, imperative tense description of the change.

User-facing notes (ones with type `fix` and `feat`) should be written so that a user can understand what has changed.
If the feature or fix does not directly impact users, consider using a different type.

✅ **Good Examples**

- `feat(media): add support for RDKit Molecules`

    It is clear to the user what the change introduces to our product.

- `fix(sdk): fix a hang caused by keyboard interrupt on Windows`

    This bug fix addressed an issue that caused the sdk to hang when hitting Ctrl-C on Windows.


❌ **Bad Examples**

- `fix(launch): fix an issue where patch is None`

    It is unclear what is referenced here.

- `feat(sdk): Adds new query to the the internal api getting the state of the run`

    It is unclear what is of importance to the user here, what do they do with that information.
    A better type would be `chore` or the title should indicate how it translates into a user-facing feature.

## Setting up your development environment

We test the library code against multiple `python` versions
and use [`pyenv`](https://github.com/pyenv/pyenv) to manage those. Install `pyenv` by running

following the instruction in [here](https://github.com/pyenv/pyenv?tab=readme-ov-file#getting-pyenv).

You would also likely want to setup pyenv-virtualenv to manage multiple environement.
For more details see: [pyenv-virtualenv](https://github.com/pyenv/pyenv-virtualenv?tab=readme-ov-file#pyenv-virtualenv)

Once you have everything installed, you can add additional python version, for example python 3.7.17, you could run the
following commmand:

```
pyenv install 3.7.17
```

Note: to switch the default python version, edit the `.python-version` file in the repository root.

## Linting the code

We are using [pre-commit hooks](https://pre-commit.com/#install) to manage oure linters and other auto-generated code.

To install `pre-commit` run the following:
```shell
pip install pre-commit
```

To install all of our pre-commit hooks run:
```shell
pre-commit install
```

If you just want to run a specific hook, like formating your code, you could run the following:
```shell
pre-commit run ruff --all-files --hook-stage pre-push
```

## Testing

### Using pytest

We use the [`pytest`](https://docs.pytest.org/) framework. Tests can be found in `tests/`.
So you could run test using pytest directly first install, all testing development found in this requirements file:

```shell
pip install -r requirements_test.txt
```

Next, you can install the test depedencies for all test, that are found in this requirements file:
```shell
pip install -r requirements_dev.txt
```
Or, just install the dependencies you need for a test.

After that you can run your test using the standard `pytest` commands. For example:

```shell
pytest tests/path-to-tests/test_file.py
```

## Auto-Generating Code

### Building protocol buffers

We use [protocol buffers](https://developers.google.com/protocol-buffers) to communicate
from the user process to the `wandb` backend process.

If you update any of the `.proto` files in `wandb/proto`, you'll need to:

- First install [`nox`](https://nox.thea.codes/en/stable/tutorial.html#installation). You could just run:
```shell
pip install nox
```

- Now you can run the proto action to build the protocol buffer files.
```shell
nox -t proto
```

Note: you only need to do that if you change any of our protocol buffer files.


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

```ipython
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

- Add a new type-annotated `SettingsData` class attribute.
- Add the new field to `wandb/proto/wandb_settings.proto` following the existing pattern.
  - Run `nox -t proto` to re-generate the python stubs.
- If the setting comes with a default value/preprocessor/additional validators/runtime hooks, add them to
  the template dictionary that the `Settings._default_props` method returns, using the same key name as
  the corresponding class variable.
  - For any setting that is only computed (from other settings) and need/should not be set/updated
    (and so does not require any validation etc.), define a hook (which does not have to depend on the setting's value)
    and use `"auto_hook": True` in the template dictionary (see e.g. the `wandb_dir` setting).
- Add tests for the new setting to `tests/wandb_settings_test.py`.
- Note that individual settings may depend on other settings through validator methods and runtime hooks,
  but the resulting directed dependency graph must be acyclic. You should re-generate the topologically-sorted
  modification order list with `nox -s auto-codegen` -- it will also automatically
  detect cyclic dependencies and throw an exception.

### Adding URLs

All URLs displayed to the user should be added to `wandb/sdk/lib/wburls.py`.  This will better
ensure that URLs do not lead to broken links.

Once you add the URL to that file you will need to run:
```shell
nox -s auto-codegen
```

### Deprecating features

Starting with version 1.0.0, `wandb` will be using [Semantic Versioning](https://semver.org/).
The major version of the library will be incremented for all backwards-incompatible changes,
including dropping support for older Python versions.

Features currently marked as deprecated will be removed in the next major version (1.0.0).

<!--
It is safe to depend on `wandb` like this: `wandb >=x.y, <(x+1)`,
where `x.y` is the first version that includes all features you need.
-->

#### Marking a feature as deprecated

To mark a feature as deprecated (and to be removed in the next major release), please follow these steps:

- Add a new field to the `Deprecated` message definition in `wandb/proto/wandb_telemetry.proto`,
  which will be used to track the to-be-deprecated feature usage.
- Rebuild protocol buffers and re-generate `wandb/proto/wandb_deprecated.py` by running `nox -s proto`.
- Finally, to mark a feature as deprecated, call `wand.sdk.lib.deprecate` in your code:

```python
from wandb.sdk.lib import deprecate

deprecate.deprecate(
    field_name=deprecate.Deprecated.deprecated_field_name,  # new_field_name from step 1
    warning_message="This feature is deprecated and will be removed in a future release.",
)
```


## Editable mode:

When using editable mode outside of the wandb directory, it is necessary to apply specific configuration settings. Due to the naming overlap between the run directory and the package, editable mode might erroneously identify the wrong files. To address this concern, several options can be considered. For more detailed information, refer to the documentation available at [this link](https://setuptools.pypa.io/en/latest/userguide/development_mode.html#strict-editable-installs). There are two approaches to achieve this:

- During installation, provide the following flags:

  ```shell
  pip install -e . --config-settings editable_mode=strict
  ```
  By doing so, editable mode will correctly identify the relevant files.


- Alternatively, you can configure it once using the following command:
  ```shell
  pip config set global.config-settings editable_mode=strict
  ```
  Once the configuration is in place, you can use the command:
  ```shell
  pip install -e .
  ```
  without any additional flags, and the strict editable mode will be applied consistently.
