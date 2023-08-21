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
To install Nexus, you will need to run the following commands (assuming you are in the root of the repository):
```bash
```bash
pip install ./nexus
```
This will install Nexus in your current Python environment.  Note that every time you make a change to the code, you
will need to re-run this command to install the changes. If you want to make changes to the code and have them
immediately available, you can install Nexus in development mode.  See the next section for instructions on how to do
that.

## Installing Nexus in Development Mode
To install Nexus in development mode, you will need to run the following commands (assuming you are in the root of the
repository):
```bash
./nexus/scripts/setup-nexus-path.sh
```
This script will also allow you to unset the Nexus path if you no longer want to use the development version of Nexus.
Follow the instructions in the script to do that.
