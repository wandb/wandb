<p align="center">
  <img src="./assets/logo-dark.svg#gh-dark-mode-only" width="600" alt="Weights & Biases" />
  <img src="./assets/logo-light.svg#gh-light-mode-only" width="600" alt="Weights & Biases" />
</p>

# Contributing to `wandb`

We at Weights & Biases ❤️ open source and welcome contributions from the community!
This guide discusses the development workflow of the `wandb` library.

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
  * [Setting up Python](#setting-up-python)
  * [Setting up Go](#setting-up-go)
  * [Building/installing the package](#building-installing-the-package)
  * [Linting the code](#linting-the-code)
  * [Auto-Generating Code](#auto-generating-code)
    + [Building protocol buffers](#building-protocol-buffers)
    + [Adding a new setting](#adding-a-new-setting)
    + [Adding URLs](#adding-urls)
    + [Deprecating features](#deprecating-features)
      - [Marking a feature as deprecated](#marking-a-feature-as-deprecated)
  * [Modifying GraphQL Schema in `wandb-core`](#modifying-graphql-schema-in--wandb-core-)
- [Testing](#testing)
  * [Using pytest](#using-pytest)

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

The W&B SDK is implemented in Python and Go.

### Setting up Python

You can use your favorite `python` version management tool, such as [`pyenv`](https://github.com/pyenv/pyenv). To install it, follow [these instructions](https://github.com/pyenv/pyenv?tab=readme-ov-file#getting-pyenv).

Optionally set up a tool to manage multiple virtual environements, for example [`pyenv-virtualenv`](https://github.com/pyenv/pyenv-virtualenv?tab=readme-ov-file#pyenv-virtualenv).

Install [`nox`](https://nox.thea.codes/en/stable/tutorial.html#installation) and [`uv`](https://github.com/astral-sh/uv) into your environment:

```shell
pip install -U nox uv
```

### Setting up Go

Install Go version `1.22.6` following the instructions [here](https://go.dev/doc/install) or using your package manager, for example:
```shell
brew install go@1.22
```

### Setting up Rust on Linux

If you are developing on a Linux machine, you will need the Rust toolchain to build the `nvidia_gpu_stats` binary used to monitor Nvidia GPUs on Linux. Refer to the official Rust [docs](https://www.rust-lang.org/tools/install) and install it by running:
```shell
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
```

### Building/installing the package

We recommend installing the `wandb` package in the editable mode with either `pip` or `uv`:

```shell
uv pip install -e .
```

If you are modifying Go code, you should rerun the command to rebuild and reinstall the package.

Alternatively, you can install `wandb-core` (the Go backend of the SDK) in development mode, by running the following command:
```shell
./core/scripts/setup-core-path.sh
```
This script will also allow you to unset the `wandb-core` path if you no longer want to use
the development version of `wandb-core`.

### Linting the code

We are using [pre-commit hooks](https://pre-commit.com/#install) to manage our linters and other auto-generated code.

To install `pre-commit` run the following:
```shell
pip install -U pre-commit
```

To install all of our pre-commit hooks run:
```shell
./core/scripts/code-checks.sh update
pre-commit install
```

If you just want to run a specific hook, for example formating your code, you could run the following:
```shell
pre-commit run ruff-format --all-files --hook-stage pre-push
```

### Auto-Generating Code

#### Building protocol buffers

We use [protocol buffers](https://developers.google.com/protocol-buffers) to communicate
from the user process to the `wandb` backend process.

If you update any of the `.proto` files in `wandb/proto`, you'll need to run the
 proto nox command to build the protocol buffer files:


```shell
nox -t proto
```

Note: you only need to do that if you change any of our protocol buffer files.

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
  modification order list with `nox -s codegen` -- it will also automatically
  detect cyclic dependencies and throw an exception.

#### Adding URLs

All URLs displayed to the user should be added to `wandb/sdk/lib/wburls.py`.  This will better
ensure that URLs do not lead to broken links.

Once you add the URL to that file you will need to run:
```shell
nox -s codegen
```

#### Deprecating features

Starting with version 1.0.0, `wandb` will be using [Semantic Versioning](https://semver.org/).
The major version of the library will be incremented for all backwards-incompatible changes,
including dropping support for older Python versions.

Features currently marked as deprecated will be removed in the next major version (1.0.0).

<!--
It is safe to depend on `wandb` like this: `wandb >=x.y, <(x+1)`,
where `x.y` is the first version that includes all features you need.
-->

##### Marking a feature as deprecated

To mark a feature as deprecated (and to be removed in the next major release), please follow these steps:

- Add a new field to the `Deprecated` message definition in `wandb/proto/wandb_telemetry.proto`,
  which will be used to track the to-be-deprecated feature usage.
- Rebuild protocol buffers and re-generate `wandb/proto/wandb_deprecated.py` by running `nox -t proto`.
- Finally, to mark a feature as deprecated, call `wand.sdk.lib.deprecate` in your code:

```python
from wandb.sdk.lib import deprecate

deprecate.deprecate(
    field_name=deprecate.Deprecated.deprecated_field_name,  # new_field_name from step 1
    warning_message="This feature is deprecated and will be removed in a future release.",
)
```

### Modifying GraphQL Schema in `wandb-core`

If there is a schema change on the Server side that affects your GraphQL API,
update `core/api/graphql/schemas/schema-latest.graphql` and run

```shell
nox -s graphql-codegen-schema-change
```

If there is no schema change and you are e.g. just adding a new query or mutation
against the schema that already supports it, DO NOT USE this nox session.
Our pre-commit hook will auto-generate the required code for you.

## Testing

### Using pytest

We use the [`pytest`](https://docs.pytest.org/) framework. Tests can be found in `tests/`.
All test dependencies should be in `requirements_dev.txt` so you could just run:

```shell
`pip install -r requirements_dev.txt`
```

After that you can run your test using the standard `pytest` commands. For example:

```shell
pytest -s -vv tests/path-to-tests/test_file.py
```
