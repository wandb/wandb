# Setting up a Development Environment

## pre-commit hooks
We are using [pre-commit](https://pre-commit.com/) to manage our pre-commit hooks.  To install `pre-commit` follow
the instructions [here](https://pre-commit.com/#install). Once `pre-commit` is installed, run the following command
from the root of the repository to set up your environment:
```bash
./nexus/scripts/code-checks.sh install
```
Now when you run `git push` the hooks will run automatically.

This step is not required, but it is highly recommended.

## Installing Nexus
To install Nexus, you will need to run the following commands (assuming you are in the
root of the repository):
```bash
pip install -r requirements_build.txt  # Install build dependencies, if needed
nox -s build-nexus install-nexus
```
This will build Nexus for your current platform and install it into your current Python environment.
Note that every time you make a change to the code, you will need to re-run this command to install
the changes. If you want to make changes to the code and have them immediately available,
you can install Nexus in development mode.

## Installing Nexus in Development Mode
To install Nexus in development mode, you will need to run the following commands
(assuming you are in the root of the repository):
```bash
./nexus/scripts/setup-nexus-path.sh
```
This script will also allow you to unset the Nexus path if you no longer want to use
the development version of Nexus. Follow the instructions in the script to do that.

## Running System Tests Locally
Install the test requirements into the current Python environment:
```bash
pip install -r requirements_test.txt  # Install test dependencies, if needed
```

A number of tests are not currently passing due to feature incompleteness.
These tests are marked with the `@pytest.mark.nexus_failure` decorator.
To list all tests that are currently failing, run the following command:
```bash
nox -s list-failing-tests-nexus
```

To run the tests excluding the failing ones locally, you will need to run the following
commands in your active Python environment (assuming you are in the root of the repository):
```bash
WANDB_REQUIRE_NEXUS=true pytest -m "not nexus_failure" tests/pytest_tests/system_tests/test_core
```
