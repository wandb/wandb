#!/usr/bin/env python
# -*- coding: utf-8 -*-

from setuptools import setup

with open('README.md') as readme_file:
    readme = readme_file.read()

requirements = [
    'Click>=6.0',
    'gql>=0.1.0',
    'requests>=2.0.0',
    'whaaaaat>=0.5.2',
    'six>=1.10.0',
    'psutil>=5.2.2',
    'watchdog>=0.8.3',
    'GitPython>=2.1.8',
    'shortuuid>=0.5.0',
    'daemonocle>=1.0.1',
    'nvidia-ml-py3>=7.352.0',
    'flask-cors>=3.0.3',
    'flask-graphql>=1.4.0',
    'graphene>=2.0.0'
]

test_requirements = [
    'mock>=2.0.0',
    'tox-pyenv>=1.0.3'
]

setup(
    name='wandb',
    version='0.5.7',
    description="A CLI and library for interacting with the Weights and Biases API.",
    long_description=readme,
    author="Chris Van Pelt",
    author_email='vanpelt@gmail.co',
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
        'Development Status :: 2 - Pre-Alpha',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: MIT License',
        'Natural Language :: English',
        "Programming Language :: Python :: 2",
        'Programming Language :: Python :: 2.6',
        'Programming Language :: Python :: 2.7',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.3',
        'Programming Language :: Python :: 3.4',
        'Programming Language :: Python :: 3.5',
    ],
    test_suite='tests',
    tests_require=test_requirements
)
