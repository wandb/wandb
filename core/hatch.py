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
    linker_flags = [
        "-s",  # Omit the symbol table and debug info.
        "-w",  # Omit the DWARF symbol table.
        # Set the Git commit variable in the main package.
        "-X",
        f"main.commit={wandb_commit_sha or ''}",
    ]
    ld_flags = [f"-ldflags={' '.join(linker_flags)}"]
    vendor_flags = ["-mod=vendor"]

    # We have to invoke Go from the directory with go.mod, hence the
    # paths relative to ./core
    cmd = [
        str(go_binary),
        "build",
        *coverage_flags,
        *race_detect_flags,
        *ld_flags,
        *output_flags,
        *vendor_flags,
        str(pathlib.Path("cmd", "wandb-core", "main.go")),
    ]
    subprocess.check_call(
        cmd,
        cwd="./core",
        env=_go_env(with_race_detection=with_race_detection, maybe_with_cgo=False),
    )


def build_nvidia_gpu_stats(
    go_binary: pathlib.Path,
    output_path: pathlib.PurePath,
) -> None:
    """Builds the nvidia_gpu_stats Go program."""
    output_flags = ["-o", str(".." / output_path)]
    ld_flags = [f"-ldflags={_go_linker_flags()}"]
    vendor_flags = ["-mod=vendor"]

    cmd = [
        str(go_binary),
        "build",
        *output_flags,
        *ld_flags,
        *vendor_flags,
        str(pathlib.Path("cmd", "nvidia-gpu-stats", "main.go")),
    ]
    # We have to invoke Go from the directory with go.mod, hence the
    # paths relative to ./core
    subprocess.check_call(
        cmd,
        cwd="./core",
        env=_go_env(with_race_detection=False, maybe_with_cgo=True),
    )


def _go_linker_flags() -> str:
    """Returns linker flags for the Go binary as a string."""
    flags = [
        "-s",  # Omit the symbol table and debug info.
        "-w",  # Omit the DWARF symbol table.
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


def _go_env(
    with_race_detection: bool,
    maybe_with_cgo: bool = False,
) -> Mapping[str, str]:
    env = os.environ.copy()

    if with_race_detection:
        # Crash if a race is detected. The default behavior is to print
        # to stderr and continue.
        env["GORACE"] = "halt_on_error=1"

    env["CGO_ENABLED"] = "0"
    if with_race_detection or maybe_with_cgo:
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
        ] or (
            # On Windows, -race requires cgo.
            system == "windows" and with_race_detection
        ):
            env["CGO_ENABLED"] = "1"

    return env
