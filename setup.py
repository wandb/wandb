#!/usr/bin/env python
# -*- coding: utf-8 -*-

from setuptools import setup

with open('README.md') as readme_file:
    readme = readme_file.read()

requirements = [
    'Click>=6.0',
    'GitPython>=1.0.0',
    'gql>=0.1.0',
    'nvidia-ml-py3>=7.352.0',
    'python-dateutil>=2.6.1',
    'requests>=2.0.0',
    'shortuuid>=0.5.0',
    'six>=1.10.0',
    'watchdog>=0.8.3',
    'psutil>=5.0.0',
    'sentry-sdk>=0.4.0',
    'subprocess32>=3.5.3',
    # Removed until we bring back the board
    # 'flask-cors>=3.0.3',
    # 'flask-graphql>=1.4.0',
    # 'graphene>=2.0.0',
]

test_requirements = [
    'mock>=2.0.0',
    'tox-pyenv>=1.0.3'
]

kubeflow_requirements = ['kubernetes', 'minio', 'google-cloud-storage', 'sh']

setup(
    name='wandb',
    version='0.6.30',
    description="A CLI and library for interacting with the Weights and Biases API.",
    long_description=readme,
    long_description_content_type="text/markdown",
    author="Weights & Biases",
    author_email='support@wandb.com',
    url='https://github.com/wandb/client',
    packages=[
        'wandb',
    ],
    package_dir={'wandb':
                 'wandb'},
    entry_points={
        'console_scripts': [
            'wandb=wandb.cli:cli',
            'wb=wandb.cli:cli',
            'wanbd=wandb.cli:cli'
        ]
    },
    include_package_data=True,
    install_requires=requirements,
    license="MIT license",
    zip_safe=False,
    keywords='wandb',
    classifiers=[
        'Development Status :: 5 - Production/Stable',
        'Intended Audience :: Developers',
        'Intended Audience :: Science/Research',
        'License :: OSI Approved :: MIT License',
        'Natural Language :: English',
        'Programming Language :: Python :: 2',
        'Programming Language :: Python :: 2.6',
        'Programming Language :: Python :: 2.7',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.3',
        'Programming Language :: Python :: 3.4',
        'Programming Language :: Python :: 3.5',
        'Topic :: Scientific/Engineering :: Artificial Intelligence',
        'Topic :: Software Development :: Libraries :: Python Modules',
        'Topic :: System :: Logging',
        'Topic :: System :: Monitoring'
    ],
    test_suite='tests',
    tests_require=test_requirements,
    extras_require={
        'kubeflow': kubeflow_requirements
    }
)
