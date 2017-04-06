===============================
Weights and Biases
===============================

.. image:: https://circleci.com/gh/wandb/client.svg?style=svg
        :target: https://circleci.com/gh/wandb/client

.. image:: https://img.shields.io/pypi/v/wandb.svg
        :target: https://pypi.python.org/pypi/wandb

.. image:: https://readthedocs.org/projects/wb-client/badge/?version=latest
        :target: https://wb-client.readthedocs.io/en/latest/?badge=latest
        :alt: Documentation Status

.. image:: https://pyup.io/repos/github/wandb/client/shield.svg
        :target: https://pyup.io/repos/github/wandb/client/
        :alt: Updates

.. image:: https://coveralls.io/repos/github/wandb/client/badge.svg?branch=master
        :target: https://coveralls.io/github/wandb/client?branch=master


A CLI and library for interacting with the Weights and Biases API.

* Free software: MIT license
* Documentation: https://wb-client.readthedocs.io


Features
--------

This library provides a CLI and python library for the `Weights & Biases<https://wanbd.ai>_` machine learning model management platform.  It makes it dead simple to upload or download revisions via the command line or your code.


Examples
--------

CLI Usage:

.. code:: shell
     
        cd myproject
        wandb init
        wandb push
        wandb pull

Client Usage:

.. code:: python

        import wandb
        client = wandb.Api()
        client.push("my_model", files=[open("some_file", "rb")])