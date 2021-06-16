"""
metric user tests.
"""

import pytest
import wandb

# TODO: improve tests by mocking some features


def test_feature_single(user_test, capsys):
    with pytest.raises(wandb.errors.UseFeatureError):
        wandb.use_feature("something")
    captured = capsys.readouterr()
    assert "unsupported feature: something" in captured.err


def test_feature_list(user_test, capsys):
    with pytest.raises(wandb.errors.UseFeatureError):
        wandb.use_feature("something,another")
    captured = capsys.readouterr()
    assert "unsupported feature: something" in captured.err
    assert "unsupported feature: another" in captured.err


def test_feature_version(user_test, capsys):
    with pytest.raises(wandb.errors.UseFeatureError):
        wandb.use_feature("something:beta")
    captured = capsys.readouterr()
    assert "unsupported feature: something" in captured.err


def test_feature_extra_args(user_test, capsys):
    with pytest.raises(wandb.errors.UseFeatureError):
        wandb.use_feature("something:beta", "unsupported")
    captured = capsys.readouterr()
    assert "ignoring unsupported parameter: unsupported" in captured.err


def test_feature_extra_kwargs(user_test, capsys):
    with pytest.raises(wandb.errors.UseFeatureError):
        wandb.use_feature("something:beta", junk="unsupported")
    captured = capsys.readouterr()
    assert "ignoring unsupported named parameter: junk" in captured.err


def test_feature_good(user_test, mocker):
    def mock_feature_test(self):
        wandb.test_method = lambda x: x + 2

    mocker.patch.object(
        wandb.wandb_sdk.wandb_feature._Features,
        "feature_test",
        mock_feature_test,
        create=True,
    )
    wandb.use_feature("test")

    assert wandb.test_method(2) == 4
