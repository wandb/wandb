from distutils import log

from setuptools import setup
from wheel.bdist_wheel import bdist_wheel, get_platform

# Package naming
# --------------
#   wandb-core:         Package containing architecture specific code

# wandb-core versioning
# ---------------------
CORE_VERSION = "0.17.0b8"

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
        bdist_wheel.run(self)


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
        cmdclass={"bdist_wheel": WrapBdistWheel},
    )
