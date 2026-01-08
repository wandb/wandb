"""Builds the orjson vendored library for fast JSON operations."""

import json
import pathlib
import shutil
import subprocess


class OrjsonBuildError(Exception):
    """Raised when building orjson fails."""


def build_orjson(
    cargo_binary: pathlib.Path,
    output_path: pathlib.Path,
) -> list[pathlib.Path]:
    """Builds the vendored `orjson` Rust library for fast JSON operations.

    NOTE: Cargo creates a cache under `./target/release` which speeds up subsequent builds,
    but may grow large over time and/or cause issues when changing the commands here.
    If you're running into problems, try deleting `./target`.

    Args:
        cargo_binary: Path to the Cargo binary, which must exist.
        output_path: The directory path where to output the binary, relative to the
            workspace root. This should be wandb/vendor/orjson.

    Returns:
        List of paths to all artifacts (library + Python files).
    """
    rust_pkg_root = pathlib.Path("./wandb/vendor/orjson")
    pysrc_dir = rust_pkg_root / "pysrc" / "orjson"
    
    # Step 1: Copy Python source files from pysrc/orjson to wandb/vendor/orjson
    # if they don't already exist at the destination
    artifacts = []
    for src_file in pysrc_dir.rglob("*"):
        if src_file.is_file():
            # Get relative path from pysrc/orjson
            rel_path = src_file.relative_to(pysrc_dir)
            dest_file = output_path / rel_path
            
            # Copy the file if it doesn't exist or is different
            dest_file.parent.mkdir(parents=True, exist_ok=True)
            if not dest_file.exists() or src_file.stat().st_mtime > dest_file.stat().st_mtime:
                shutil.copy2(src_file, dest_file)
            
            artifacts.append(dest_file)

    # Step 2: Build the Rust extension
    cmd = (
        str(cargo_binary),
        "build",
        "--release",
        "--message-format=json",
        "--lib",
    )

    try:
        cargo_output = subprocess.check_output(cmd, cwd=rust_pkg_root)
    except subprocess.CalledProcessError as e:
        raise OrjsonBuildError(
            "Failed to build the vendored `orjson` Rust library. If you didn't"
            " break the build, you may need to install Rust; see"
            " https://www.rust-lang.org/tools/install."
            "\n\n"
            "As a workaround, you can set the WANDB_BUILD_SKIP_ORJSON"
            " environment variable to true to skip this step and build a wandb"
            " package without the vendored orjson library."
        ) from e

    built_library_path = _get_cdylib_path(cargo_output)

    # Step 3: Copy the built library to the output location with the correct name
    output_path.mkdir(parents=True, exist_ok=True)
    
    import platform
    
    # Determine the correct extension name for a Python extension module
    # We need to match Python's naming convention for extension modules
    system = platform.system().lower()
    if system == "windows":
        extension = ".pyd"
    else:
        # On Unix-like systems, Python extensions use .so
        extension = ".so"
    
    # The extension module should be named "orjson.{extension}"
    target_name = output_path / f"orjson{extension}"
    
    # Copy the built library to the target location
    shutil.copy2(built_library_path, target_name)
    target_name.chmod(0o755)
    
    artifacts.append(target_name)
    
    return artifacts


def _get_cdylib_path(cargo_output: bytes) -> pathlib.Path:
    """Returns the path to the orjson cdylib.

    Args:
        cargo_output: The output from `cargo build` with
            --message-format="json".

    Returns:
        The path to the library.

    Raises:
        OrjsonBuildError: if the path could not be determined.
    """
    for line in cargo_output.splitlines():
        try:
            msg = json.loads(line)
            # Look for compiler artifact messages with filenames
            if msg.get("reason") == "compiler-artifact":
                filenames = msg.get("filenames", [])
                target = msg.get("target", {})
                # We want the cdylib for orjson
                if target.get("name") == "orjson" and target.get("kind") == ["cdylib"]:
                    if filenames:
                        return pathlib.Path(filenames[0])
        except (json.JSONDecodeError, KeyError):
            continue

    raise OrjsonBuildError(
        "Failed to find the `orjson` library. `cargo build` output:\n"
        + cargo_output.decode("utf-8", errors="replace"),
    )

