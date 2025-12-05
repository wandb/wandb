from unittest import mock

import pytest
import wandb
from wandb.apis.public import runs


@pytest.fixture(autouse=True)
def patch_server_features(monkeypatch: pytest.MonkeyPatch) -> None:
    """Prevent unit tests from attempting to contact the real server."""
    monkeypatch.setattr(
        runs,
        "_server_provides_project_id_for_run",
        lambda *args, **kwargs: False,
    )
    monkeypatch.setattr(
        runs,
        "_server_provides_internal_id_for_project",
        lambda *args, **kwargs: False,
    )


@pytest.mark.parametrize(
    "field,value,expected",
    [
        ("config", '{"test": "test"}', {"test": "test"}),
        ("summaryMetrics", '{"test": "test"}', {"test": "test"}),
        ("systemMetrics", '{"test": "test"}', {"test": "test"}),
    ],
    ids=["config", "summaryMetrics", "systemMetrics"],
)
@pytest.mark.usefixtures("patch_apikey", "skip_verify_login")
def test_create_run_with_string_attrs(field, value, expected):
    run = wandb.apis.public.Run(
        client=wandb.Api().client,
        entity="test",
        project="test",
        run_id="test",
        attrs={field: value},
    )
    assert getattr(run, field) == expected


@pytest.mark.parametrize(
    "field,value",
    [
        ("config", {"test": "test"}),
        ("summaryMetrics", {"test": "test"}),
        ("systemMetrics", {"test": "test"}),
    ],
    ids=["config", "summaryMetrics", "systemMetrics"],
)
@pytest.mark.usefixtures("patch_apikey", "skip_verify_login")
def test_create_run_with_dictionary_attrs_already_parsed(field, value):
    with mock.patch.object(wandb, "login", mock.MagicMock()):
        run = wandb.apis.public.Run(
            client=wandb.Api().client,
            entity="test",
            project="test",
            run_id="test",
            attrs={field: value},
        )
        assert getattr(run, field) == value


@pytest.mark.parametrize(
    "field,value",
    [
        ("config", 1),
        ("summaryMetrics", 1),
        ("systemMetrics", 1),
    ],
    ids=["config", "summaryMetrics", "systemMetrics"],
)
@pytest.mark.usefixtures("patch_apikey", "skip_verify_login")
def test_create_run_with_dictionary__throws_type_error(field, value):
    with mock.patch.object(wandb, "login", mock.MagicMock()):
        with pytest.raises(wandb.errors.CommError):
            wandb.apis.public.Run(
                client=wandb.Api().client,
                entity="test",
                project="test",
                run_id="test",
                attrs={
                    field: value,
                },
            )


@pytest.mark.parametrize(
    "field,value,expected",
    [
        ("config", '{"test": "test\ttest"}', {"test": "test\ttest"}),
        ("summaryMetrics", '{"test": "test\ttest"}', {"test": "test\ttest"}),
        ("systemMetrics", '{"test": "test\ttest"}', {"test": "test\ttest"}),
    ],
    ids=["config", "summaryMetrics", "systemMetrics"],
)
@pytest.mark.usefixtures("patch_apikey", "skip_verify_login")
def test_create_run_with_control_characters(field, value, expected):
    with mock.patch.object(wandb, "login", mock.MagicMock()):
        run = wandb.apis.public.Run(
            client=wandb.Api().client,
            entity="test",
            project="test",
            run_id="test",
            attrs={field: value},
        )
        assert getattr(run, field) == expected
