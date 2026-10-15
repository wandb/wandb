"""Builds the wandb-symon binary that collects system metrics."""

import json
import pathlib
import subprocess


class WandbSymonBuildError(Exception):
    """Raised when building wandb-symon service fails."""


def build_wandb_symon(
    cargo_binary: pathlib.Path,
    output_path: pathlib.Path,
    target_triple: str | None = None,
) -> None:
    """Builds the `wandb-symon` Rust binary that collects system metrics.

    NOTE: Cargo creates a cache under `./target/release`, which speeds up
    subsequent builds, but may grow large over time and/or cause issues
    when changing the commands here. If you're running into problems,
    try deleting `./target`.

    Args:
        cargo_binary: Path to the Cargo binary, which must exist.
        output_path: The path where to output the binary, relative to the
            workspace root.
        target_triple: Rust target triple, or None to build for the host.
    """
    rust_pkg_root = pathlib.Path("./symon")

    cmd = [
        str(cargo_binary),
        "build",
        "--locked",
        "--release",
        "--bin",
        "wandb-symon",
        "--message-format=json",
    ]
    if target_triple:
        cmd.extend(("--target", target_triple))

    try:
        cargo_output = subprocess.check_output(cmd, cwd=rust_pkg_root, text=True)
    except subprocess.CalledProcessError as e:
        raise WandbSymonBuildError(
            "Failed to build the `wandb-symon` Rust binary. If you didn't"
            " break the build, you may need to install Rust; see"
            " https://www.rust-lang.org/tools/install."
            "\n\n"
            "As a workaround, you can set the WANDB_BUILD_SKIP_WANDB_SYMON"
            " environment variable to true to skip this step and build a wandb"
            " package that doesn't collect system metrics."
        ) from e
    for line in cargo_output.splitlines():
        if executable := json.loads(line).get("executable"):
            built_binary_path = pathlib.Path(executable)
            break
    else:
        raise WandbSymonBuildError(
            "Failed to find the `wandb-symon` binary. `cargo build` output:\n"
            + cargo_output,
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    built_binary_path.replace(output_path)
    output_path.chmod(0o755)
