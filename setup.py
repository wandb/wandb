#!/usr/bin/env python
# -*- coding: utf-8 -*-

from setuptools import setup

with open('README.md') as readme_file:
    readme = readme_file.read()

requirements = [
    'Click>=7.0',
    'GitPython>=1.0.0',
    'gql==0.2.0',
    'nvidia-ml-py3>=7.352.0',
    'python-dateutil>=2.6.1',
    'requests>=2.0.0',
    'shortuuid>=0.5.0',
    'six>=1.10.0',
    'watchdog>=0.8.3',
    'PyYAML>=3.10',
    'psutil>=5.0.0',
    'sentry-sdk>=0.4.0',
    'subprocess32>=3.5.3',
    'docker-pycreds>=0.4.0',
    'configparser>=3.8.1',
]

test_requirements = [
    'mock>=2.0.0',
    'tox-pyenv>=1.0.3'
]

gcp_requirements = ['google-cloud-storage']
aws_requirements = ['boto3']

kubeflow_requirements = ['kubernetes', 'minio', 'google-cloud-storage', 'sh']

setup(
    name='wandb',
    version='0.9.2',
    description="A CLI and library for interacting with the Weights and Biases API.",
    long_description=readme,
    long_description_content_type="text/markdown",
    author="Weights & Biases",
    author_email='support@wandb.com',
    url='https://github.com/wandb/client',
    packages=[
        'wandb'
    ],
    package_dir={'wandb': 'wandb'},
    entry_points={
        'console_scripts': [
            'wandb=wandb.cli:cli',
            'wb=wandb.cli:cli',
            'wanbd=wandb.cli:cli',
            'wandb-docker-run=wandb.cli:docker_run'
        ]
    },
    include_package_data=True,
    install_requires=requirements,
    license="MIT license",
    zip_safe=False,
    keywords='wandb',
    python_requires='>=2.7, !=3.0.*, !=3.1.*, !=3.2.*, !=3.3.*',
    classifiers=[
        'Development Status :: 5 - Production/Stable',
        'Intended Audience :: Developers',
        'Intended Audience :: Science/Research',
        'License :: OSI Approved :: MIT License',
        'Natural Language :: English',
        'Programming Language :: Python :: 2',
        'Programming Language :: Python :: 2.7',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.4',
        'Programming Language :: Python :: 3.5',
        'Programming Language :: Python :: 3.6',
        'Programming Language :: Python :: 3.7',
        'Topic :: Scientific/Engineering :: Artificial Intelligence',
        'Topic :: Software Development :: Libraries :: Python Modules',
        'Topic :: System :: Logging',
        'Topic :: System :: Monitoring'
    ],
    test_suite='tests',
    tests_require=test_requirements,
    extras_require={
        'kubeflow': kubeflow_requirements,
        'gcp': gcp_requirements,
        'aws': aws_requirements
    }
)
