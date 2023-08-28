#!/usr/bin/env python
"""wandb setup."""

from setuptools import setup

with open("package_readme.md") as readme_file:
    readme = readme_file.read()

with open("requirements.txt") as requirements_file:
    requirements = requirements_file.read().splitlines()

with open("requirements_sweeps.txt") as sweeps_requirements_file:
    sweeps_requirements = sweeps_requirements_file.read().splitlines()

gcp_requirements = ["google-cloud-storage"]
aws_requirements = ["boto3"]
azure_requirements = ["azure-identity", "azure-storage-blob"]
grpc_requirements = ["grpcio>=1.27.2"]
kubeflow_requirements = ["kubernetes", "minio", "google-cloud-storage", "sh"]
media_requirements = [
    "numpy",
    "moviepy",
    "pillow",
    "bokeh",
    "soundfile",
    "plotly",
    "rdkit-pypi",
]
launch_requirements = [
    "awscli",
    "azure-identity",
    "azure-containerregistry",
    "azure-storage-blob",
    "boto3",
    "botocore",
    "chardet",
    "google-auth",
    "google-cloud-artifact-registry",
    "google-cloud-compute",
    "google-cloud-storage",
    "iso8601",
    "kubernetes",
    "optuna",
    "nbconvert",
    "nbformat",
    "typing_extensions",
]

models_requirements = ["cloudpickle"]

async_requirements = [
    "httpx>=0.22.0",  # 0.23.0 dropped Python 3.6; we can upgrade once we drop it too
]

perf_requirements = ["orjson"]


setup(
    name="wandb",
    version="0.15.9",
    description="A CLI and library for interacting with the Weights and Biases API.",
    long_description=readme,
    long_description_content_type="text/markdown",
    author="Weights & Biases",
    author_email="support@wandb.com",
    url="https://github.com/wandb/wandb",
    packages=["wandb"],
    package_dir={"wandb": "wandb"},
    package_data={"wandb": ["py.typed"]},
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
    python_requires=">=3.6",
    classifiers=[
        "Development Status :: 5 - Production/Stable",
        "Intended Audience :: Developers",
        "Intended Audience :: Science/Research",
        "License :: OSI Approved :: MIT License",
        "Natural Language :: English",
        "Programming Language :: Python :: 3 :: Only",
        "Programming Language :: Python :: 3.6",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Topic :: Scientific/Engineering :: Artificial Intelligence",
        "Topic :: Software Development :: Libraries :: Python Modules",
        "Topic :: System :: Logging",
        "Topic :: System :: Monitoring",
    ],
    extras_require={
        "kubeflow": kubeflow_requirements,
        "gcp": gcp_requirements,
        "aws": aws_requirements,
        "azure": azure_requirements,
        "grpc": grpc_requirements,
        "media": media_requirements,
        "sweeps": sweeps_requirements,
        "launch": launch_requirements,
        "models": models_requirements,
        "async": async_requirements,
        "perf": perf_requirements,
    },
)
