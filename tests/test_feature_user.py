"""
metric user tests.
"""

import pytest
import wandb

# TODO: improve tests by mocking some features


def test_feature_single(user_test):
    wandb.use_feature("something")


def test_feature_list(user_test):
    wandb.use_feature("something,another")


def test_feature_version(user_test):
    wandb.use_feature("something:beta")

