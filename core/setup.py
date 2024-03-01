import os
import pathlib
import platform
import sysconfig
from distutils import log

from setuptools import setup
from setuptools.command.build_py import build_py

# Package naming
# --------------
#   wandb-core:         Package containing architecture specific code

# wandb-core versioning
# ---------------------
CORE_VERSION = "0.17.0b9"

PACKAGE = "wandb_core"


# TODO: Remove?
# class WrapBdistWheel(bdist_wheel):
#     def get_tag(self):
#         # Use the default implementation to get python and abi tags
#         python, abi = bdist_wheel.get_tag(self)[:2]
#         # Use the wheel package function to determine platform tag
#         plat_name = get_platform(self.bdist_dir)
#         # todo: add MACOSX_DEPLOYMENT_TARGET to support older macs
#         return python, abi, plat_name

#     def run(self):
#         super().run()


class CustomBuildPy(build_py):
    """Custom step to copy pre-built binary artifacts into bin/."""

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
                f" (from sysconfig.get_platform() == '{sysplat}')"
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
        cmdclass={"build_py": CustomBuildPy},
    )
