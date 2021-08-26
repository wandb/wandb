#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""wandb setup."""

import warnings

from setuptools import setup


with open("package_readme.md") as readme_file:
    readme = readme_file.read()

with open("requirements.txt") as requirements_file:
    requirements = requirements_file.read().splitlines()

try:
    with open("wandb/sweeps_engine/requirements.txt") as sweeps_requirements_file:
        sweeps_requirements = sweeps_requirements_file.read().splitlines()
except FileNotFoundError:
    warnings.warn(
        "Sweeps module is not present, unable to determine "
        "extra requirements for sweeps. Will not be able to build "
        "sweeps extras locally. Run `make submodule-update` to get module."
    )
    sweeps_requirements = []

test_requirements = ["mock>=2.0.0", "tox-pyenv>=1.0.3"]

gcp_requirements = ["google-cloud-storage"]
aws_requirements = ["boto3"]
grpc_requirements = ["grpcio==1.27.2"]
kubeflow_requirements = ["kubernetes", "minio", "google-cloud-storage", "sh"]
media_requirements = ["numpy", "moviepy", "pillow", "bokeh", "soundfile", "plotly"]
launch_requirements = ["docker", "jupyter-repo2docker", "chardet", "iso8601"]

setup(
    name="wandb",
    version="0.12.1",
    description="A CLI and library for interacting with the Weights and Biases API.",
    long_description=readme,
    long_description_content_type="text/markdown",
    author="Weights & Biases",
    author_email="support@wandb.com",
    url="https://github.com/wandb/client",
    packages=["wandb"],
    package_dir={"wandb": "wandb"},
    package_data={"wandb": ["py.typed", "sweeps_engine/requirements.txt"]},
    entry_points={
        "console_scripts": [
            "wandb=wandb.cli.cli:cli",
            "wb=wandb.cli.cli:cli",
        ]
    },
    include_package_data=True,
    install_requires=requirements,
    license="MIT license",
    zip_safe=False,
    # keywords='wandb',
    python_requires=">=3.6",
    classifiers=[
        "Development Status :: 5 - Production/Stable",
        "Intended Audience :: Developers",
        "Intended Audience :: Science/Research",
        "License :: OSI Approved :: MIT License",
        "Natural Language :: English",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.5",
        "Programming Language :: Python :: 3.6",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Topic :: Scientific/Engineering :: Artificial Intelligence",
        "Topic :: Software Development :: Libraries :: Python Modules",
        "Topic :: System :: Logging",
        "Topic :: System :: Monitoring",
    ],
    test_suite="tests",
    tests_require=test_requirements,
    extras_require={
        "kubeflow": kubeflow_requirements,
        "gcp": gcp_requirements,
        "aws": aws_requirements,
        "grpc": grpc_requirements,
        "media": media_requirements,
        "sweeps": sweeps_requirements,
        "launch": launch_requirements,
    },
)

# if os.name == "nt" and sys.version_info >= (3, 6):
#     legacy_env_var = "PYTHONLEGACYWINDOWSSTDIO"
#     if legacy_env_var not in os.environ:
#         if os.system("setx " + legacy_env_var + " 1") != 0:
#             raise Exception("Error setting environment variable " + legacy_env_var)
