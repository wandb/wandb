import os
import pathlib
import sys

import click
from core import winibuild as build_core
from core.pkg.monitor.apple import winibuild as build_applestats

from . import print, subprocess, workspace


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
@click.option("--install", "should_install", is_flag=True, default=False)
def release(should_install):
    """Creates a release build of the wandb-core wheel.

    The output wheel is ./core/dist/wandb_core-*, with the exact name selected
    by setuptools based on the library version and target platform.
    """
    _package(is_testing=False)

    if should_install:
        _do_install()


@package.command()
@click.option("--install", "should_install", is_flag=True, default=False)
def testing(should_install):
    """Creates a build of the wandb-core wheel for testing.

    The output wheel is ./core/dist/wandb_core-*, with the exact name selected
    by setuptools based on the library version and target platform.
    """
    _package(is_testing=True)

    if should_install:
        _do_install()


@package.command()
def install():
    """Installs the built wandb-core wheel.

    Assumes that `./wini package release` or `./wini package testing`
    was invoked. Runs `pip install` on the output.
    """
    _do_install()


def _do_install():
    try:
        wheel_files = [
            f
            for f in os.listdir("./core/dist/")
            if f.startswith("wandb_core-") and f.endswith(".whl")
        ]
    except FileNotFoundError:
        print.error(
            "No ./core/dist/ directory. Did you forget to run"
            " `./wini package release`?"
        )
        sys.exit(1)

    if len(wheel_files) == 0:
        print.error(
            "No wandb_core wheel found. Did you forget to run"
            " `./wini package release`?"
        )
        sys.exit(1)

    if len(wheel_files) > 1:
        print.error(
            "Found more than one wandb_core wheel, which is not currently supported."
        )
        sys.exit(1)

    subprocess.check_call(
        [
            "pip",
            "install",
            "--force-reinstall",
            f"./core/dist/{wheel_files[0]}",
        ]
    )


def _package(is_testing: bool):
    build_core.build_nexus(
        output_path=pathlib.PurePath("./core/wandb_core/wandb-core"),
        with_code_coverage=is_testing,
    )

    if workspace.target_os() == workspace.OS.DARWIN:
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
