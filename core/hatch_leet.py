"""Builds wandb-leet."""

import pathlib
import subprocess
from typing import Optional

from .hatch import _go_env, _go_linker_flags


def build_wandb_leet(
    go_binary: pathlib.Path,
    output_path: pathlib.PurePath,
    with_cgo: bool,
    wandb_commit_sha: Optional[str],
    target_system,
    target_arch,
) -> None:
    """Builds the wandb-leet Go module.

    Args:
        go_binary: Path to the Go binary, which must exist.
        output_path: The path where to output the binary, relative to the
            workspace root.
        with_cgo: Whether to build the binary with CGO enabled.
        wandb_commit_sha: The Git commit hash we're building from, if this
            is the https://github.com/wandb/wandb repository. Otherwise, an
            empty string.
        target_system: The target operating system (GOOS) or an empty string
            to use the current OS.
        target_arch: The target architecture (GOARCH) or an empty string
            to use the current architecture.
    """
    output_flags = ["-o", str(".." / output_path)]

    ld_flags = [f"-ldflags={_go_linker_flags(wandb_commit_sha=wandb_commit_sha)}"]

    vendor_flags = ["-mod=vendor"]

    # We have to invoke Go from the directory with go.mod, hence the
    # paths relative to ./core
    subprocess.check_call(
        [
            str(go_binary),
            "build",
            *ld_flags,
            *output_flags,
            *vendor_flags,
            str(pathlib.Path("cmd", "wandb-leet", "main.go")),
        ],
        cwd="./core",
        env=_go_env(
            with_cgo=with_cgo,
            with_race_detection=False,
            target_system=target_system,
            target_arch=target_arch,
        ),
    )
