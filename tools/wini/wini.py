import os
import pathlib
import sys

import click
from core import winibuild as build_core
from core.pkg.monitor.apple import winibuild as build_applestats

from . import print, subprocess, workspace


@click.group()
def wini():
    """Collection of scripts for the wandb repository.

    'Wini' stands for 'W(eights and Biases) I(nitialize), and also it is a
    reference to Winnie-the-Pooh who doesn't wear pants, because we wanted
    to use https://www.pantsbuild.org originally, but it didn't have a few
    features we needed.
    """


@wini.group()
def build():
    """Commands to build parts of the application."""


@build.command(name="wandb-core-artifacts")
@click.option("--coverage", "with_coverage", is_flag=True, default=False)
def build_wandb_core_artifacts(with_coverage):
    """Builds artifacts to include in the wandb-core wheel.

    The artifacts are stored in ./core/wandb_core/ to be included in the
    wandb-core Python wheel.
    """
    _build_wandb_core_artifacts(with_coverage=with_coverage)


def _build_wandb_core_artifacts(*, with_coverage):
    build_core.build_wandb_core(
        output_path=pathlib.PurePath("./core/wandb_core/wandb-core"),
        with_code_coverage=with_coverage,
    )

    if workspace.target_os() == workspace.OS.DARWIN:
        build_applestats.build_applestats(
            output_path=pathlib.PurePath("./core/wandb_core/AppleStats")
        )


@wini.group()
def package():
    """Commands to produce packages for testing and distribution."""


@package.command(name="wandb-core")
@click.option(
    "--install",
    "should_install",
    help="Install the wheel locally using pip install.",
    is_flag=True,
    default=False,
)
@click.option(
    "--coverage",
    "with_coverage",
    help="Build Go with code coverage enabled (go build -cover).",
    is_flag=True,
    default=False,
)
def package_wandb_core(should_install, with_coverage):
    """Creates the wandb-core wheel, optionally installing it."""
    _build_wandb_core_artifacts(with_coverage=with_coverage)

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

    if should_install:
        _do_install()


@package.command()
def install():
    """Installs the built wandb-core wheel.

    Assumes that `./wini package wandb-core` was invoked. Runs
    `pip install` on the output.
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
            " `./wini package wandb-core`?"
        )
        sys.exit(1)

    if len(wheel_files) == 0:
        print.error(
            "No wandb_core wheel found. Did you forget to run"
            " `./wini package wandb-core`?"
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


if __name__ == "__main__":
    wini()
