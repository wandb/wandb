import os
import pathlib
import platform
import sysconfig
from distutils import log

from setuptools import setup
from setuptools.command.build_py import build_py
from wheel.bdist_wheel import bdist_wheel

# Package naming
# --------------
#   wandb-core:         Package containing architecture specific code

# wandb-core versioning
# ---------------------
CORE_VERSION = "0.17.0b9"

PACKAGE = "wandb_core"


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

    def initialize_options(self):
        super().initialize_options()

        # We always build wheels for the platform we're running on.
        #
        # See https://packaging.python.org/en/latest/specifications/platform-compatibility-tags/#platform-tag
        #
        # For manylinux: https://github.com/pypa/auditwheel upgrades "linux"
        # platform tags to "manylinux" for us. cibuildwheel runs auditwheel
        # in the "repair wheel" step.
        self.plat_name = sysconfig.get_platform().replace("-", "_")


class CustomBuildPy(build_py):
    """Custom step to copy pre-built binary artifacts into the package."""

    def run(self):
        pkgdir = pathlib.Path(__file__).parent / PACKAGE

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

            if dest.exists():
                dest.unlink()

            os.symlink(file, dest)

        super().run()


if __name__ == "__main__":
    log.set_verbosity(log.INFO)

    setup(
        name="wandb-core",
        version=CORE_VERSION,
        description="W&B Core Library",
        long_description=open("README.md", encoding="utf-8").read(),
        long_description_content_type="text/markdown",
        packages=[PACKAGE],
        zip_safe=False,
        include_package_data=True,
        license="MIT license",
        python_requires=">=3.6",
        cmdclass={
            "bdist_wheel": CustomWheel,
            "build_py": CustomBuildPy,
        },
    )
