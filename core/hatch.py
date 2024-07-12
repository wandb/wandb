"""Builds wandb-core."""

import os
import pathlib
import platform
import subprocess
from typing import Mapping, Optional


def build_wandb_core(
    go_binary: pathlib.Path,
    output_path: pathlib.PurePath,
    with_code_coverage: bool,
    with_race_detection: bool,
    wandb_commit_sha: Optional[str],
) -> None:
    """Builds the wandb-core Go module.

    Args:
        go_binary: Path to the Go binary, which must exist.
        output_path: The path where to output the binary, relative to the
            workspace root.
        with_code_coverage: Whether to build the binary with code coverage
            support, using `go build -cover`.
        with_race_detection: Whether to build the binary with race detection
            enabled, using `go build -race`.
        wandb_commit_sha: The Git commit hash we're building from, if this
            is the https://github.com/wandb/wandb repository. Otherwise, an
            empty string.
    """
    coverage_flags = ["-cover"] if with_code_coverage else []
    race_detect_flags = ["-race"] if with_race_detection else []
    output_flags = ["-o", str(".." / output_path)]
    ld_flags = [f"-ldflags={_go_linker_flags(wandb_commit_sha)}"]
    vendor_flags = ["-mod=vendor"]

    # We have to invoke Go from the directory with go.mod, hence the
    # paths relative to ./core
    subprocess.check_call(
        [
            str(go_binary),
            "build",
            *coverage_flags,
            *race_detect_flags,
            *ld_flags,
            *output_flags,
            *vendor_flags,
            str(pathlib.Path("cmd", "wandb-core", "main.go")),
        ],
        cwd="./core",
        env=_go_env(with_race_detection=with_race_detection),
    )


def _go_linker_flags(wandb_commit_sha: Optional[str]) -> str:
    """Returns linker flags for the Go binary as a string."""
    flags = [
        "-s",  # Omit the symbol table and debug info.
        "-w",  # Omit the DWARF symbol table.
        # Set the Git commit variable in the main package.
        "-X",
        f"main.commit={wandb_commit_sha or ''}",
    ]

    return " ".join(flags)


def _go_env(with_race_detection: bool) -> Mapping[str, str]:
    env = os.environ.copy()

    if with_race_detection:
        # Crash if a race is detected. The default behavior is to print
        # to stderr and continue.
        env["GORACE"] = "halt_on_error=1"

    system = platform.system().lower()

    # On Windows, -race requires cgo.
    if system == "windows" and with_race_detection:
        env["CGO_ENABLED"] = "1"

    return env
