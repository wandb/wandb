import cwsandbox
import wandb.sandbox as wandb_sandbox
from wandb.sandbox import Secret
from wandb.sandbox._secret import WANDB_SECRET_STORE

_HIDDEN_EXPORT_NAMES = {"AuthHeaders", "set_auth_mode"}
_OVERRIDDEN_EXPORT_NAMES = {"Secret"}


def test_sandbox_wrapper_reexports_cwsandbox_public_api() -> None:
    expected_export_names = set(cwsandbox.__all__) - _HIDDEN_EXPORT_NAMES

    assert expected_export_names == set(wandb_sandbox.__all__)
    assert _HIDDEN_EXPORT_NAMES.isdisjoint(set(wandb_sandbox.__all__))

    for name in expected_export_names - _OVERRIDDEN_EXPORT_NAMES:
        assert getattr(wandb_sandbox, name) is getattr(cwsandbox, name)


def test_sandbox_wrapper_uses_wandb_secret_override() -> None:
    assert "Secret" in wandb_sandbox.__all__
    assert Secret is not cwsandbox.Secret

    secret = Secret(name="MY_SECRET")

    assert isinstance(secret, cwsandbox.Secret)
    assert secret.name == "MY_SECRET"
    assert secret.store == WANDB_SECRET_STORE

    secret = Secret(store="not-default-store", name="MY_SECRET")
    assert secret.store == "not-default-store"
