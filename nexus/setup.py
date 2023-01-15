"""yea setup."""

from setuptools import setup


setup(
    name="wandb-nexus",
    version="0.0.1.dev1",
    description="Wandb core",
    packages=["wandb_nexus"],
    zip_safe=False,
    include_package_data=True,
    license="MIT license",
    python_requires=">=3.6",
)
