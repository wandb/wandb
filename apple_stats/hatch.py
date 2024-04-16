"""Builds the AppleStats Swift binary for monitoring system metrics."""

import pathlib
import subprocess


def build_applestats(output_path: pathlib.PurePath) -> None:
    """Builds the AppleStats universal Swift binary.

    NOTE: Swift creates a cache in a directory called ".build/" which speeds
    up subsequent builds but can cause issues when changing the commands here.
    If you're running into problems, try deleting ".build/".

    Args:
        output_path: The path where to output the binary, relative to the
            workspace root.
    """
    source_path = pathlib.Path("./apple_stats")

    def arch_output_path(arch: str) -> pathlib.Path:
        return (
            source_path  # (break line for readability)
            / ".build"
            / f"{arch}-apple-macosx"
            / "release"
            / "AppleStats"
        )

    base_cmd = [
        "swift",
        "build",
        "--configuration",
        "release",
        "-Xswiftc",
        "-cross-module-optimization",
    ]

    cmd_x86_64 = base_cmd + ["--arch", "x86_64"]
    cmd_arm64 = base_cmd + ["--arch", "arm64"]

    subprocess.check_call(cmd_x86_64, cwd=source_path)
    subprocess.check_call(cmd_arm64, cwd=source_path)

    subprocess.check_call(
        [
            "lipo",
            "-create",
            arch_output_path("x86_64"),
            arch_output_path("arm64"),
            "-output",
            str(output_path),
        ]
    )
