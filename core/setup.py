import os
import pathlib
import platform
from distutils import log

from setuptools import setup
from setuptools.command.build_py import build_py
from wheel.bdist_wheel import bdist_wheel, get_platform

# Package naming
# --------------
#   wandb-core:         Package containing architecture specific code

# wandb-core versioning
# ---------------------
CORE_VERSION = "0.17.0b9"

PACKAGE = "wandb_core"


class WrapBdistWheel(bdist_wheel):
    def get_tag(self):
        # Use the default implementation to get python and abi tags
        python, abi = bdist_wheel.get_tag(self)[:2]
        # Use the wheel package function to determine platform tag
        plat_name = get_platform(self.bdist_dir)
        # todo: add MACOSX_DEPLOYMENT_TARGET to support older macs
        return python, abi, plat_name

    def run(self):
        super().run()


class CustomBuildPy(build_py):
    """Custom step to copy pre-built binary artifacts into bin/."""

    def run(self):
        pkgdir = pathlib.Path(__file__).parent / PACKAGE

        # Clean the "bin/" directory.
        bindir = pkgdir / "bin"
        if bindir.exists():
            for file in bindir.iterdir():
                file.unlink()
        else:
            bindir.mkdir()

        # Figure out the normalized architecture name for our current arch.
        arch = platform.machine().lower()
        print(f"setup.py: platform.machine() returned '{arch}'")
        if arch == "arm64":
            arch = "aarch64"
        elif arch == "amd64":
            arch = "x86_64"

        # Symlink the artifacts into bin/. The build system will copy the
        # actual files into the wheel.
        archdir = pkgdir.parent / "wandb_core_artifacts" / arch
        for file in archdir.iterdir():
            os.symlink(file, bindir / file.name)

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
            "bdist_wheel": WrapBdistWheel,
            "build_py": CustomBuildPy,
        },
    )
