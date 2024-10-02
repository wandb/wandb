"""Builds the AppleStats Swift binary for monitoring system metrics on arm64 macOS."""

import pathlib
import subprocess


class AppleStatsBuildError(Exception):
    """Raised when building AppleStats fails."""


def build_applestats(output_path: pathlib.PurePath) -> None:
    """Builds the AppleStats Swift binary for arm64.

    NOTE: Swift creates a cache in a directory called ".build/" which speeds
    up subsequent builds but can cause issues when changing the commands here.
    If you're running into problems, try deleting ".build/".

    Args:
        output_path: The path where to output the binary, relative to the
            workspace root.
    """
    source_path = pathlib.Path("./apple_stats")

    cmd = [
        "swift",
        "build",
        "--configuration",
        "release",
        "-Xswiftc",
        "-cross-module-optimization",
        "--arch",
        "arm64",
    ]

    try:
        subprocess.check_call(cmd, cwd=source_path)
    except subprocess.CalledProcessError as e:
        raise AppleStatsBuildError(
            "Failed to build the `apple_stats` Swift binary. If you didn't"
            " break the build, you may need to update your Xcode command line"
            " tools; try running `softwareupdate --list` to see if a new Xcode"
            " version is available, and then `softwareupdate --install` it"
            " if so."
            "\n\n"
            "As a workaround, you can set the WANDB_BUILD_SKIP_APPLE"
            " environment variable to true to skip this step and build a wandb"
            " package that doesn't collect Apple system metrics."
        ) from e

    built_binary = (
        source_path  # break line for readability
        / ".build"
        / "arm64-apple-macosx"
        / "release"
        / "AppleStats"
    )
    subprocess.check_call(["cp", str(built_binary), str(output_path)])
