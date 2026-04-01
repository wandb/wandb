"""Build script for arrow-rs-wrapper."""

from __future__ import annotations

import json
import pathlib
import platform
import subprocess


class ArrowRsWrapperBuildError(Exception):
    """Raised when building arrow-rs-wrapper fails."""


def build_arrow_rs_wrapper(
    cargo_binary: pathlib.Path,
    output_path: pathlib.Path,
    target_system: str | None = None,
    target_arch: str | None = None,
) -> None:
    """Build the arrow-rs-wrapper Rust library.

    NOTE: Cargo creates a cache under `./target/release`
    which speeds up subsequent builds, but may grow large over time
    and/or cause issues when changing the commands here.
    If you're running into problems, try deleting `./target`.

    Args:
        cargo_binary: Path to the cargo binary.
        output_path: Path where the built library should be placed.
        target_system: Target OS (darwin, linux, windows).
        target_arch: Target architecture (amd64, arm64).
    """
    arrow_rs_wrapper_dir = pathlib.Path(__file__).parent

    # Determine the library name based on target system
    if target_system == "windows":
        lib_name = "arrow_rs_wrapper.dll"
    elif target_system == "darwin":
        lib_name = "libarrow_rs_wrapper.dylib"
    else:  # linux or None (default to .so)
        lib_name = "libarrow_rs_wrapper.so"

    cmd = [
        str(cargo_binary),
        "build",
        "--release",
        "--message-format=json",
        "--manifest-path",
        str(arrow_rs_wrapper_dir / "Cargo.toml"),
    ]

    # Only pass --target for actual cross-compilation. Passing it for
    # native builds forces Rust into cross-compilation mode, which fails
    # in manylinux containers that lack cross-compilation sysroots.
    if target_system and target_arch:
        target_triple = _get_rust_target_triple(target_system, target_arch)
        if target_triple and not _is_native_target(target_triple):
            cmd.extend(["--target", target_triple])

    try:
        cargo_output = subprocess.check_output(cmd, cwd=arrow_rs_wrapper_dir)
    except subprocess.CalledProcessError as e:
        raise ArrowRsWrapperBuildError(
            "Failed to build the `arrow-rs-wrapper` Rust library. If you didn't"
            + " break the build, you may need to install Rust; see"
            + " https://www.rust-lang.org/tools/install."
        ) from e

    built_binary_path = _get_library_path(cargo_output, lib_name)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    built_binary_path.replace(output_path)
    output_path.chmod(0o755)


def _get_library_path(cargo_output: bytes, lib_name: str) -> pathlib.Path:
    """Returns the path to the arrow-rs-wrapper library.

    Args:
        cargo_output: The output from `cargo build` with
            --message-format="json".
        lib_name: The expected library name.

    Returns:
        The path to the library.

    Raises:
        ArrowRsWrapperBuildError: if the path could not be determined.
    """
    for line in cargo_output.splitlines():
        try:
            message = json.loads(line)
            # Look for compiler-artifact messages with cdylib target kind
            if message.get("reason") == "compiler-artifact":
                target = message.get("target", {})
                if "cdylib" in target.get("kind", []):
                    # Get the first file from filenames (the library)
                    filenames = message.get("filenames", [])
                    if filenames:
                        path = pathlib.Path(filenames[0])
                        if path.name == lib_name:
                            return path
        except (json.JSONDecodeError, KeyError):
            continue

    raise ArrowRsWrapperBuildError(
        f"Failed to find the `arrow-rs-wrapper` library ({lib_name}). `cargo build` output:\n"
        + cargo_output.decode("utf-8", errors="replace"),
    )


def _get_rust_target_triple(target_system: str, target_arch: str) -> str | None:
    """Convert Go-style OS/arch to Rust target triple."""
    # Map of (goos, goarch) -> Rust target triple
    target_map = {
        ("darwin", "amd64"): "x86_64-apple-darwin",
        ("darwin", "arm64"): "aarch64-apple-darwin",
        ("linux", "amd64"): "x86_64-unknown-linux-gnu",
        ("linux", "arm64"): "aarch64-unknown-linux-gnu",
        ("windows", "amd64"): "x86_64-pc-windows-msvc",
        ("windows", "arm64"): "aarch64-pc-windows-msvc",
    }

    return target_map.get((target_system, target_arch))


def _is_native_target(target_triple: str) -> bool:
    """Check if the Rust target triple matches the current host platform."""
    host_os = platform.system().lower()
    host_arch = platform.machine().lower()

    native_triples = {
        ("linux", "x86_64"): "x86_64-unknown-linux-gnu",
        ("linux", "aarch64"): "aarch64-unknown-linux-gnu",
        ("darwin", "x86_64"): "x86_64-apple-darwin",
        ("darwin", "arm64"): "aarch64-apple-darwin",
    }

    return native_triples.get((host_os, host_arch)) == target_triple
