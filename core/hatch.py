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
    wandb_commit_sha: Optional[str],
) -> None:
    """Builds the wandb-core Go module.

    Args:
        go_binary: Path to the Go binary, which must exist.
        output_path: The path where to output the binary, relative to the
            workspace root.
        with_code_coverage: Whether to build the binary with code coverage
            support, using `go build -cover`.
        wandb_commit_sha: The Git commit hash we're building from, if this
            is the https://github.com/wandb/wandb repository. Otherwise, an
            empty string.
    """
    coverage_flags = ["-cover"] if with_code_coverage else []
    output_flags = ["-o", str(".." / output_path)]
    ld_flags = [f"-ldflags={_go_linker_flags(wandb_commit_sha)}"]

    # We have to invoke Go from the directory with go.mod, hence the
    # paths relative to ./core
    subprocess.check_call(
        [
            str(go_binary),
            "build",
            *coverage_flags,
            *ld_flags,
            *output_flags,
            str(pathlib.Path("cmd", "wandb-core", "main.go")),
        ],
        cwd="./core",
        env=_go_env(),
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

    if platform.system().lower() == "linux" and platform.machine().lower() in (
        "x86_64",
        "amd64",
    ):
        ext_ld_flags = " ".join(
            [
                # Use https://en.wikipedia.org/wiki/Gold_(linker)
                "-fuse-ld=gold",
                # Set the --weak-unresolved-symbols option in gold, converting
                # unresolved symbols to weak references. This is necessary to
                # build a Go binary with cgo on Linux, where the NVML libraries
                # needed for Nvidia GPU monitoring may not be available at build time.
                "-Wl,--weak-unresolved-symbols",
            ]
        )
        flags += ["-extldflags", f'"{ext_ld_flags}"']

    return " ".join(flags)


def _go_env() -> Mapping[str, str]:
    env = os.environ.copy()

    system = platform.system().lower()
    arch = platform.machine().lower()

    if (system, arch) in [
        # Use cgo on AMD64 Linux to build dependencies needed for GPU metrics.
        ("linux", "amd64"),
        ("linux", "x86_64"),
        # Use cgo on ARM64 macOS for the gopsutil dependency, otherwise several
        # system metrics are unavailable.
        ("darwin", "arm64"),
        ("darwin", "aarch64"),
    ]:
        env["CGO_ENABLED"] = "1"

    return env
