"""Builds the AppleStats Swift binary for monitoring system metrics."""

import pathlib
import platform
import subprocess


def build_applestats(
    output_path: pathlib.PurePath,
) -> None:
    """Builds the AppleStats Swift binary.

    Args:
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
    ]

    source_path = pathlib.PurePath("./core/pkg/monitor/apple")

    # TODO: It's unfortunately not clear how to control the output, so we must
    # hardcode it like this.
    swift_output = (
        source_path
        / ".build"
        / f"{platform.machine().lower()}-apple-macosx"
        / "release"
        / "AppleStats"
    )

    print(f"Running: {cmd}")
    subprocess.check_call(cmd, cwd=source_path)

    subprocess.check_call(
        [
            "cp",
            str(swift_output),
            str(output_path),
        ]
    )
