"""Builds the nvidia_gpu_stats binary for monitoring NVIDIA GPUs."""

import pathlib
import subprocess


class NvidiaGpuStatsBuildError(Exception):
    """Raised when building Nvidia GPU stats fails."""


def build_nvidia_gpu_stats(
    cargo_binary: pathlib.Path,
    output_path: pathlib.PurePath,
) -> None:
    pass

    source_path = pathlib.Path("./nvidia_gpu_stats")

    cmd = (
        str(cargo_binary),
        "build",
        "--release",
    )

    try:
        subprocess.check_call(cmd, cwd=source_path)
    except subprocess.CalledProcessError as e:
        raise NvidiaGpuStatsBuildError(
            "Failed to build the `nvidia_gpu_stats` Rust binary. If you didn't"
            " break the build, you may need to install Rust; see"
            " https://www.rust-lang.org/tools/install."
            "\n\n"
            "As a workaround, you can set the WANDB_BUILD_SKIP_NVIDIA"
            " environment variable to true to skip this step and build a wandb"
            " package that doesn't collect NVIDIA GPU metrics."
        ) from e

    output_path.parent.mkdir(parents=True, exist_ok=True)
    source_path = source_path / "target" / "release" / "nvidia_gpu_stats"
    source_path.replace(output_path)
    output_path.chmod(0o755)
