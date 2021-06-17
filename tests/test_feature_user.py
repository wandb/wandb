"""
metric user tests.
"""

import pytest
import wandb


@pytest.fixture
def feature_mock(mocker):
    cleanup = []

    def fn(feature, func):
        cleanup.append(feature)
        mocker.patch.object(
            wandb.wandb_sdk.wandb_feature._Features,
            "feature_" + feature,
            func,
            create=True,
        )

    yield fn
    for feature in cleanup:
        wandb.__dict__.pop("feature_" + feature, None)


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


def test_feature_good(user_test, feature_mock):
    def mock_feature_test(self):
        wandb.feature_test = lambda x: x + 2

    feature_mock("test", mock_feature_test)
    wandb.use_feature("test")

    assert wandb.feature_test(2) == 4
