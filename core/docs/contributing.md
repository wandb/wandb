# Setting up a Development Environment

## pre-commit hooks
We are using [pre-commit](https://pre-commit.com/) to manage our pre-commit hooks.  To install `pre-commit` follow
the instructions [here](https://pre-commit.com/#install). Once `pre-commit` is installed, run the following command
from the root of the repository to set up your environment:
```shell
./nexus/scripts/code-checks.sh install
```
Now when you run `git push` the hooks will run automatically.

This step is not required, but it is highly recommended.

## Installing WandB Core
To install wandb-core, you will need to run the following commands (assuming you are in the
root of the repository):
```shell
pip install -r requirements_build.txt  # Install build dependencies, if needed
nox -s build-core install-core
```
This will build wandb-core for your current platform and install it into your current Python environment.
Note that every time you make a change to the code, you will need to re-run this command to install
the changes. If you want to make changes to the code and have them immediately available,
you can install wandb-core in development mode.

## Installing WandB Core in Development Mode
To install wandb-core in development mode, you will need to run the following commands
(assuming you are in the root of the repository):
```shell
./nexus/scripts/setup-nexus-path.sh
```
This script will also allow you to unset the wandb-core path if you no longer want to use
the development version of wandb-core. Follow the instructions in the script to do that.

## Running System Tests Locally
Install the test requirements into the current Python environment:
```shell
pip install -r requirements_test.txt  # Install test dependencies, if needed
```

A number of tests are not currently passing due to feature incompleteness.
These tests are marked with the `@pytest.mark.wandb_core_failure` decorator.
To list all tests that are currently failing, run the following command:
```shell
nox -s list-failing-tests-wandb-core
```

To run the tests excluding the failing ones locally, you will need to run the following
commands in your active Python environment (assuming you are in the root of the repository):
```shell
pytest -m "not wandb_core_failure" tests/pytest_tests/system_tests/test_core
```

## Modifying GraphQL Schema
If there is a schema change on the Server side that affects your GraphQL API,
update `nexus/api/graphql/schemas/schema-latest.graphql` and run

```shell
nox -s graphql-codegen-schema-change
```

If there is no schema change and you are e.g. just adding a new query or mutation
against the schema that already supports it, DO NOT USE this nox session.
Our pre-commit hook will auto-generate the required code for you.
