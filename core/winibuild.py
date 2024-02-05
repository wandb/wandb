"""Builds wandb-core."""

import os
import pathlib
import subprocess

from tools.wini import workspace


def build_nexus(
    output_path: pathlib.PurePath,
    with_code_coverage: bool,
) -> None:
    """Builds the wandb-core Go module.

    Args:
        output_path: The path where to output the binary, relative to the
            workspace root.
        with_code_coverage: Whether to build the binary with code coverage
            support, using `go build -cover`.
    """
    coverage_flags = ["-cover"] if with_code_coverage else []
    output_flags = ["-o", str(".." / output_path)]
    ld_flags = [f"-ldflags={_go_linker_flags()}"]

    # We have to invoke Go from the directory with go.mod, hence the
    # paths relative to ./core
    cmd = [
        "go",
        "build",
        *coverage_flags,
        *ld_flags,
        *output_flags,
        "cmd/wandb-core/main.go",
    ]

    print(f"Running: {cmd}")
    subprocess.check_call(cmd, cwd="./core", env=_go_env())


def _go_linker_flags() -> str:
    """Returns linker flags for the Go binary as a string."""
    flags = [
        "-s",  # Omit the symbol table and debug info.
        "-w",  # Omit the DWARF symbol table.
        # Set the Git commit variable in the main package.
        "-X",
        f"main.commit={workspace.git_commit_sha()}",
    ]

    if workspace.osarch() == (workspace.OS.LINUX, workspace.Arch.AMD64):
        ext_ld_flags = " ".join(
            [
                # Use https://en.wikipedia.org/wiki/Gold_(linker)
                "-fuse-ld=gold",
                # Set the --weak-unresolved-symbols option in gold, converting
                # unresolved symbols to weak references.
                #
                # TODO: why?
                "-Wl,--weak-unresolved-symbols",
            ]
        )
        flags += ["-extldflags", f'"{ext_ld_flags}"']

    return " ".join(flags)


def _go_env() -> dict[str, str]:
    env = os.environ.copy()

    if workspace.osarch() in [
        # Use cgo on ARM Linux to build dependencies needed for GPU metrics.
        (workspace.OS.LINUX, workspace.Arch.AMD64),
        # Use cgo on ARM Mac for the gopsutil dependency, otherwise
        # several system metrics are unavailable.
        (workspace.OS.DARWIN, workspace.Arch.AMD64),
    ]:
        env["CGO_ENABLED"] = "1"

    return env
