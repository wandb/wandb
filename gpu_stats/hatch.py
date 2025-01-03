"""Builds the gpu_stats binary for monitoring NVIDIA and Apple ARM GPUs."""

import json
import pathlib
import subprocess


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
        "--message-format=json",
    )

    try:
        cargo_output = subprocess.check_output(cmd, cwd=rust_pkg_root)
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

    built_binary_path = _get_executable_path(cargo_output)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    built_binary_path.replace(output_path)
    output_path.chmod(0o755)


def _get_executable_path(cargo_output: bytes) -> pathlib.Path:
    """Returns the path to the gpu_stats binary.

    Args:
        cargo_output: The output from `cargo build` with
            --message-format="json".

    Returns:
        The path to the binary.

    Raises:
        GpuStatsBuildError: if the path could not be determined.
    """
    for line in cargo_output.splitlines():
        path = json.loads(line).get("executable")
        if path:
            return pathlib.Path(path)

    raise GpuStatsBuildError(
        "Failed to find the `gpu_stats` binary. `cargo build` output:\n"
        + str(cargo_output),
    )
