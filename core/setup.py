from distutils import log

from setuptools import setup

# Package naming
# --------------
#   wandb-core:         Package containing architecture specific code

# wandb-core versioning
# ---------------------
CORE_VERSION = "0.17.0b9"

PACKAGE = "wandb_core"


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
    )
