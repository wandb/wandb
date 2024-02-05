import pathlib
import subprocess

import click

from . import workspace
from core import winibuild as build_core
from core.pkg.monitor.apple import winibuild as build_applestats


@click.group()
def wini():
    """Ad-hoc tools for the wandb repository.

    'Wini' stands for 'W(eights and Biases) I(nitialize), and also it is a
    reference to Winnie-the-Pooh who doesn't wear pants, because we wanted
    to use https://www.pantsbuild.org originally, but it didn't have a few
    features we needed.
    """


@wini.group()
def package():
    """Commands to produce packages for testing and distribution."""


@package.command()
def release():
    """Creates a release build of the wandb-core wheel."""
    _package(is_testing=False)


@package.command()
def testing():
    """Creates a build of the wandb-core wheel for testing."""
    _package(is_testing=True)


def _package(is_testing: bool):
    build_core.build_nexus(
        output_path=pathlib.PurePath("./core/wandb_core/wandb-core"),
        with_code_coverage=is_testing,
    )

    if workspace.current_os() == workspace.OS.DARWIN:
        build_applestats.build_applestats(
            output_path=pathlib.PurePath("./core/wandb_core/AppleStats")
        )

    subprocess.run(
        [
            "python",
            "-m",
            "build",
            "-w",  # Only build the wheel.
            "-n",  # Disable building the project in an isolated venv.
            "-x",  # Do not check that build deps are installed.
            "./core",
        ]
    )


if __name__ == "__main__":
    wini()
