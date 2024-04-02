"""Builds the AppleStats Swift binary for monitoring system metrics."""

import pathlib

from tools.wini import arch, subprocess


def build_applestats(
    architecture: arch.Arch,
    output_path: pathlib.PurePath,
) -> None:
    """Builds the AppleStats Swift binary.

    NOTE: Swift creates a cache in a directory called ".build/" which speeds
    up subsequent builds but can cause issues when changing the commands here.
    If you're running into problems, try deleting ".build/".

    Args:
        architecture: The machine architecture to target.
        output_path: The path where to output the binary, relative to the
            workspace root.
    """
    cmd = [
        "swift",
        "build",
        "--configuration",
        "release",
        "-Xswiftc",
        "-cross-module-optimization",
        "--arch",
        architecture.swift_name,
    ]

    source_path = pathlib.PurePath("./apple_stats")

    # TODO: It's unfortunately not clear how to control the output, so we must
    # hardcode it like this.
    swift_output = (
        source_path
        / ".build"
        / f"{architecture.swift_name}-apple-macosx"
        / "release"
        / "AppleStats"
    )

    subprocess.check_call(cmd, cwd=source_path)

    subprocess.check_call(
        [
            "cp",
            str(swift_output),
            str(output_path),
        ]
    )
