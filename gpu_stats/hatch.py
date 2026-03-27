"""Builds the gpu_stats binary for monitoring NVIDIA and Apple ARM GPUs."""

import pathlib
import subprocess
import sys


class GpuStatsBuildError(Exception):
    """Raised when building GPU stats service fails."""


def build_gpu_stats(
    cargo_binary: pathlib.Path,
    output_path: pathlib.Path,
) -> None:
    """Builds the `gpu_stats` Rust binary for monitoring NVIDIA and Apple ARM GPUs.

    NOTE: Cargo creates a cache under `./target/release` which speeds up subsequent builds,
    but may grow large over time and/or cause issues when changing the commands here.
    If you're running into problems, try deleting `./target`.

    Args:
        cargo_binary: Path to the Cargo binary, which must exist.
        output_path: The path where to output the binary, relative to the
            workspace root.
    """
    rust_pkg_root = pathlib.Path("./gpu_stats")

    cmd = (
        str(cargo_binary),
        "build",
        "--release",
        "--bin",
        "gpu_stats",
    )

    try:
        subprocess.run(cmd, cwd=rust_pkg_root, check=True)
    except subprocess.CalledProcessError as e:
        raise GpuStatsBuildError(
            "Failed to build the `gpu_stats` Rust binary. If you didn't"
            " break the build, you may need to install Rust; see"
            " https://www.rust-lang.org/tools/install."
            "\n\n"
            "As a workaround, you can set the WANDB_BUILD_SKIP_GPU_STATS"
            " environment variable to true to skip this step and build a wandb"
            " package that doesn't collect NVIDIA and Apple ARM GPU stats."
        ) from e

    binary_name = "gpu_stats.exe" if sys.platform == "win32" else "gpu_stats"
    built_binary_path = rust_pkg_root / "target" / "release" / binary_name

    output_path.parent.mkdir(parents=True, exist_ok=True)
    built_binary_path.replace(output_path)
    output_path.chmod(0o755)
