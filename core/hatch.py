"""Builds wandb-core."""

import os
import pathlib
import subprocess
from typing import Mapping, Optional


def build_wandb_core(
    go_binary: pathlib.Path,
    output_path: pathlib.PurePath,
    with_code_coverage: bool,
    with_race_detection: bool,
    with_cgo: bool,
    wandb_commit_sha: Optional[str],
    target_system,
    target_arch,
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
        with_cgo: Whether to build the binary with CGO enabled.
        wandb_commit_sha: The Git commit hash we're building from, if this
            is the https://github.com/wandb/wandb repository. Otherwise, an
            empty string.
        target_system: The target operating system (GOOS) or an empty string
            to use the current OS.
        target_arch: The target architecture (GOARCH) or an empty string
            to use the current architecture.
    """
    coverage_flags = ["-cover"] if with_code_coverage else []
    race_detect_flags = ["-race"] if with_race_detection else []
    output_flags = ["-o", str(".." / output_path)]

    ld_flags = [f"-ldflags={_go_linker_flags(wandb_commit_sha=wandb_commit_sha)}"]

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
        env=_go_env(
            with_cgo=with_cgo,
            with_race_detection=with_race_detection,
            target_system=target_system,
            target_arch=target_arch,
        ),
    )


def _go_linker_flags(wandb_commit_sha: Optional[str]) -> str:
    """Returns linker flags for the Go binary as a string."""
    flags = [
        "-s",  # Omit the symbol table and debug info.
        "-w",  # Omit the DWARF symbol table.
        # Set the Git commit variable in the main package.
        "-X",
        f"main.commit={wandb_commit_sha or 'unknown'}",
    ]

    return " ".join(flags)


def _go_env(
    with_cgo: bool,
    with_race_detection: bool,
    target_system: str,
    target_arch: str,
) -> Mapping[str, str]:
    env = os.environ.copy()

    env["GOOS"] = target_system
    env["GOARCH"] = target_arch

    # CGO can be enabled if, for example, FIPS compliance is required, as it
    # relies on being able to load SSL libraries dynamically - and therefore
    # building with CGO_ENABLED=1.
    # See https://github.com/wandb/wandb/issues/10131.
    env["CGO_ENABLED"] = "1" if with_cgo else "0"

    if with_race_detection:
        # Crash if a race is detected. The default behavior is to print
        # to stderr and continue.
        env["GORACE"] = "halt_on_error=1"
        # -race requires cgo.
        env["CGO_ENABLED"] = "1"

    if target_system == "darwin" and target_arch == "amd64":
        # When CGO is disabled, the Go compiler's internal linker does not respect
        # the MACOSX_DEPLOYMENT_TARGET value to lower the minimum OS version, which we rely on
        # for building wheels for MacOS 10.x in CI. Instead, it embeds a minimum target
        # based on the SDK in the CI runner, which as of 2025-02-20 is 11.0.
        # To work around this, we enable CGO and force the Go compiler to use
        # the system linker, which respects MACOSX_DEPLOYMENT_TARGET.
        env["CGO_ENABLED"] = "1"

    return env
