"""Builds the wandb-xpu binary for monitoring hardware accelerators."""

import pathlib
import subprocess
import sys


class WandbXpuBuildError(Exception):
    """Raised when building wandb-xpu service fails."""


def build_wandb_xpu(
    cargo_binary: pathlib.Path,
    output_path: pathlib.Path,
) -> None:
    """Builds the `wandb-xpu` Rust binary for monitoring hardware accelerators.

    `wandb-xpu` supports NVIDIA and AMD GPU, Apple ARM CPU/GPU, and Google TPU.

    NOTE: Cargo creates a cache under `./target/release`, which speeds up
    subsequent builds, but may grow large over time and/or cause issues
    when changing the commands here. If you're running into problems,
    try deleting `./target`.

    Args:
        cargo_binary: Path to the Cargo binary, which must exist.
        output_path: The path where to output the binary, relative to the
            workspace root.
    """
    rust_pkg_root = pathlib.Path("./xpu")

    cmd = (
        str(cargo_binary),
        "build",
        "--release",
        "--bin",
        "wandb-xpu",
    )

    try:
        subprocess.run(cmd, cwd=rust_pkg_root, check=True)
    except subprocess.CalledProcessError as e:
        raise WandbXpuBuildError(
            "Failed to build the `wandb-xpu` Rust binary. If you didn't"
            " break the build, you may need to install Rust; see"
            " https://www.rust-lang.org/tools/install."
            "\n\n"
            "As a workaround, you can set the WANDB_BUILD_SKIP_WANDB_XPU"
            " environment variable to true to skip this step and build a wandb"
            " package that doesn't collect hardware accelerator metrics."
        ) from e

    binary_name = "wandb-xpu.exe" if sys.platform == "win32" else "wandb-xpu"
    built_binary_path = rust_pkg_root / "target" / "release" / binary_name

    output_path.parent.mkdir(parents=True, exist_ok=True)
    built_binary_path.replace(output_path)
    output_path.chmod(0o755)
