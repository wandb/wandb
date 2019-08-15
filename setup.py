#!/usr/bin/env python
# -*- coding: utf-8 -*-

from setuptools import setup
import os
from glob import glob
import sys
from setupbase import (
    create_cmdclass, install_npm, ensure_targets,
    combine_commands, ensure_python
)
from os.path import join as pjoin
from distutils import log

here = os.path.dirname(os.path.abspath(__file__))


cmdclass = create_cmdclass(
    'js',
    data_files_spec=[
        ('share/jupyter/lab/extensions',
         os.path.join('wandb', 'jupyter', 'lab', 'js', 'lab-dist'), '*.tgz'),
        ('etc/jupyter/jupyter_notebook_config.d', 'jupyter-config/jupyter_notebook_config.d',
         'wandb.json'),
    ],
)
cmdclass['js'] = ensure_targets([pjoin(here, 'jupyter-config', 'jupyter_notebook_config.d', 'wandb.json')])
if "--build-js" in sys.argv:
    cmdclass['js'] = combine_commands(
        install_npm(
            path=os.path.join(here, 'wandb', 'jupyter', 'lab', 'js'),
            build_dir=os.path.join(here, 'wandb', 'jupyter', 'lab', 'js', 'lib'),
            source_dir=os.path.join(here, 'wandb', 'jupyter', 'lab', 'js', 'src'),
            build_cmd='build:labextension',
        ),
        ensure_targets([
            pjoin(here, 'wandb', 'jupyter', 'lab', 'js', 'lib', 'index.js'),
        ]),
    )
    sys.argv.remove("--build-js")
else:
    log.warn("Not building jupyter extension, pass --build-js to build the extension.")

with open('README.md') as readme_file:
    readme = readme_file.read()

requirements=[
    'Click>=7.0',
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
    'docker-pycreds>=0.4.0',
    # Removed until we bring back the board
    # 'flask-cors>=3.0.3',
    # 'flask-graphql>=1.4.0',
    # 'graphene>=2.0.0',
]

test_requirements=[
    'mock>=2.0.0',
    'tox-pyenv>=1.0.3'
]

kubeflow_requirements=['kubernetes', 'minio', 'google-cloud-storage', 'sh']

args = {"name": 'wandb',
    "version": '0.8.8',
    "description": "A CLI and library for interacting with the Weights and Biases API.",
    "long_description": readme,
    "long_description_content_type": "text/markdown",
    "author": "Weights & Biases",
    "author_email": 'support@wandb.com',
    "url": 'https://github.com/wandb/client',
    "packages": [
        'wandb'
    ],
    "package_dir": {'wandb': 'wandb'},
    "entry_points": {
        'console_scripts': [
            'wandb=wandb.cli:cli',
            'wb=wandb.cli:cli',
            'wanbd=wandb.cli:cli',
            'wandb-docker-run=wandb.cli:docker_run'
        ]
    },
    "cmdclass": cmdclass,
    "include_package_data": True,
    "install_requires": requirements,
    "license": "MIT license",
    "zip_safe": False,
    "keywords": ['wandb', 'tensorflow', 'pytorch', 'keras', 'jupyter', 'jupyterlab'],
    "python_requires": '>=2.7, !=3.0.*, !=3.1.*, !=3.2.*, !=3.3.*',
    "classifiers": [
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
    "test_suite": 'tests',
    "tests_require": test_requirements,
    "extras_require": {
        'kubeflow': kubeflow_requirements
    }
}

setup(**args)
