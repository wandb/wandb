import os
import pathlib
import platform
import sysconfig
from distutils import log

from setuptools import setup
from setuptools.command.build_py import build_py
from wheel.bdist_wheel import bdist_wheel, get_platform


class CustomWheel(bdist_wheel):
    """Overrides the wheel tag with the proper information.

    wandb-core is an extremely simple wheel that doesn't depend on a particular
    Python implementation or a Python ABI but includes platform-specific
    binaries.

    Python wheel names describe the environments they can run in using platform
    compatibility tags:
    https://packaging.python.org/en/latest/specifications/platform-compatibility-tags/

    The platform tag cannot be inferred, so we set it manually.
    """

    # Why override get_tag() instead of initialize_options()?
    #
    # Setting self.plat_name in initialize_options() would be the proper way to
    # do this, but see the macOS issue described below.
    def get_tag(self):
        python, abi = super().get_tag()[:2]

        # We always build wheels for the platform we're running on.
        #
        # See https://packaging.python.org/en/latest/specifications/platform-compatibility-tags/#platform-tag
        #
        # For manylinux: https://github.com/pypa/auditwheel upgrades "linux"
        # platform tags to "manylinux" for us. cibuildwheel runs auditwheel
        # in the "repair wheel" step.
        #
        # Ideally we would use `sysconfig.get_platform()` here, but due to
        # historical changes in macOS versioning, it did not return a minor
        # version for new macOS-es until Python 3.12. This unfortunately
        # confuses pip, resulting in errors like
        #
        #   ERROR: wandb_core-0.17.0b9-py3-none-macosx_14_arm64.whl is not a supported wheel on this platform.
        #
        # See https://github.com/python/cpython/issues/102362.
        #
        # For unknown reasons, discovered purely by experimentation, the issue
        # is resolved by overriding `bdist_wheel.get_tag()` and using the
        # `wheel` package's `get_platform()` function. Notably, neither sysconfig
        # in `get_tag()` nor `get_platform()` in `initialize_options()` works.
        plat_name = get_platform(self.bdist_dir)

        return python, abi, plat_name


class CustomBuildPy(build_py):
    """Custom step to copy pre-built binary artifacts into the package."""

    def run(self):
        pkgdir = pathlib.Path(__file__).parent / "wandb_core"

        # Figure out the normalized architecture name for our current arch.
        arch = platform.machine().lower()
        if arch == "arm64":
            arch = "aarch64"
        elif arch == "amd64":
            arch = "x86_64"

        # We use cibuildwheel to create platform-specific wheels.
        #
        # On the ARM64 macOS-14 GitHub runner, platform.machine() sometimes
        # returns x86_64 instead of arm64. This seems to be caused by
        # cibuildwheel downloading an x86_64 Python on older machines, causing
        # it to run via Rosetta, which (probably) causes `uname -m` to return
        # x86_64.
        #
        # In these cases, `sysconfig.get_platform()` seems to still have the
        # correct information.
        sysplat = sysconfig.get_platform()
        if sysplat.endswith("arm64"):
            arch = "aarch64"
            print(
                f"setup.py: target architecture is '{arch}' "
                f"(from sysconfig.get_platform() == '{sysplat}')"
            )
        else:
            print(f"setup.py: target architecture is '{arch}'")

        # Symlink the artifacts into bin/. The build system will copy the
        # actual files into the wheel.
        archdir = pkgdir.parent / "wandb_core_artifacts" / arch
        for file in archdir.iterdir():
            dest = pkgdir / file.name

            try:
                # missing_ok=True doesn't exist in Python 3.7
                dest.unlink()
            except FileNotFoundError:
                pass

            os.symlink(file.resolve(), dest)

        super().run()


if __name__ == "__main__":
    log.set_verbosity(log.INFO)

    setup(
        cmdclass={
            "bdist_wheel": CustomWheel,
            "build_py": CustomBuildPy,
        },
    )
