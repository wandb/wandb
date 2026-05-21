import cwsandbox
import pytest
import wandb.sandbox as wandb_sandbox
import wandb.sandbox._sandbox as sandbox_module
from wandb.errors import UsageError
from wandb.sandbox import Secret
from wandb.sandbox._secret import WANDB_SECRET_STORE

_HIDDEN_EXPORT_NAMES = {"AuthHeaders", "set_auth_mode"}
_OVERRIDDEN_EXPORT_NAMES = {"Sandbox", "Secret", "Session"}
_PLACEMENT_OVERRIDE_FIELDS = ("profile_ids", "profile_names", "runner_ids")
_GPU_RESOURCE_VALUES = (
    cwsandbox.ResourceOptions(gpu={"count": 1}),
    {"gpu": 1},
    {"requests": {"cpu": "1"}, "gpu": {"count": 1}},
)
_UNSUPPORTED_EGRESS_NETWORK_VALUES = (
    cwsandbox.NetworkOptions(egress_mode="private"),
    {"egress_mode": "private"},
)
_SUPPORTED_NETWORK_VALUES = (
    cwsandbox.NetworkOptions(egress_mode="internet"),
    cwsandbox.NetworkOptions(egress_mode="none"),
    cwsandbox.NetworkOptions(ingress_mode="public", exposed_ports=(8080,)),
    {"egress_mode": "internet"},
    {"egress_mode": "none"},
)


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


@pytest.mark.parametrize("field", _PLACEMENT_OVERRIDE_FIELDS)
def test_sandbox_wrapper_rejects_placement_overrides(field: str) -> None:
    with pytest.raises(UsageError, match=f"placement overrides.*{field}"):
        wandb_sandbox.Sandbox(**{field: []})


@pytest.mark.parametrize("field", _PLACEMENT_OVERRIDE_FIELDS)
def test_sandbox_wrapper_rejects_default_placement_overrides(field: str) -> None:
    defaults = cwsandbox.SandboxDefaults(**{field: ("placement-1",)})

    with pytest.raises(UsageError, match=f"placement overrides.*{field}"):
        wandb_sandbox.Sandbox(defaults=defaults)


@pytest.mark.parametrize("resources", _GPU_RESOURCE_VALUES)
def test_sandbox_wrapper_rejects_gpu_resources(resources) -> None:
    with pytest.raises(UsageError, match="GPU resources"):
        wandb_sandbox.Sandbox(resources=resources)


@pytest.mark.parametrize("resources", _GPU_RESOURCE_VALUES)
def test_sandbox_wrapper_rejects_default_gpu_resources(resources) -> None:
    defaults = cwsandbox.SandboxDefaults(resources=resources)

    with pytest.raises(UsageError, match="GPU resources"):
        wandb_sandbox.Sandbox(defaults=defaults)


@pytest.mark.parametrize("network", _UNSUPPORTED_EGRESS_NETWORK_VALUES)
def test_sandbox_wrapper_rejects_unsupported_egress_modes(network) -> None:
    with pytest.raises(UsageError, match="egress modes.*private"):
        wandb_sandbox.Sandbox(network=network)


@pytest.mark.parametrize("network", _UNSUPPORTED_EGRESS_NETWORK_VALUES)
def test_sandbox_wrapper_rejects_default_unsupported_egress_modes(network) -> None:
    defaults = cwsandbox.SandboxDefaults(network=network)

    with pytest.raises(UsageError, match="egress modes.*private"):
        wandb_sandbox.Sandbox(defaults=defaults)


@pytest.mark.parametrize("network", _SUPPORTED_NETWORK_VALUES)
def test_sandbox_wrapper_allows_supported_network_options(network) -> None:
    wandb_sandbox.Sandbox(network=network)


@pytest.mark.parametrize("field", _PLACEMENT_OVERRIDE_FIELDS)
def test_sandbox_session_rejects_placement_overrides(field: str) -> None:
    session = wandb_sandbox.Session()

    with pytest.raises(UsageError, match=f"placement overrides.*{field}"):
        session.sandbox(**{field: ["placement-1"]})


@pytest.mark.parametrize("field", _PLACEMENT_OVERRIDE_FIELDS)
def test_sandbox_session_rejects_default_placement_overrides(field: str) -> None:
    with pytest.raises(UsageError, match=f"placement overrides.*{field}"):
        wandb_sandbox.Session(defaults={field: ["placement-1"]})


@pytest.mark.parametrize("field", _PLACEMENT_OVERRIDE_FIELDS)
def test_sandbox_session_rejects_positional_default_placement_overrides(
    field: str,
) -> None:
    with pytest.raises(UsageError, match=f"placement overrides.*{field}"):
        wandb_sandbox.Session({field: ["placement-1"]})


@pytest.mark.parametrize("resources", _GPU_RESOURCE_VALUES)
def test_sandbox_session_rejects_gpu_resources(resources) -> None:
    session = wandb_sandbox.Session()

    with pytest.raises(UsageError, match="GPU resources"):
        session.sandbox(resources=resources)


@pytest.mark.parametrize("resources", _GPU_RESOURCE_VALUES)
def test_sandbox_session_rejects_default_gpu_resources(resources) -> None:
    with pytest.raises(UsageError, match="GPU resources"):
        wandb_sandbox.Session(defaults={"resources": resources})


@pytest.mark.parametrize("network", _UNSUPPORTED_EGRESS_NETWORK_VALUES)
def test_sandbox_session_rejects_unsupported_egress_modes(network) -> None:
    session = wandb_sandbox.Session()

    with pytest.raises(UsageError, match="egress modes.*private"):
        session.sandbox(network=network)


@pytest.mark.parametrize("network", _UNSUPPORTED_EGRESS_NETWORK_VALUES)
def test_sandbox_session_rejects_default_unsupported_egress_modes(network) -> None:
    with pytest.raises(UsageError, match="egress modes.*private"):
        wandb_sandbox.Session(defaults={"network": network})


def test_sandbox_session_forwards_kwargs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = []
    sandbox = object()

    def fake_base_sandbox(self, **kwargs):
        calls.append((self, kwargs))
        return sandbox

    monkeypatch.setattr(sandbox_module._BaseSession, "sandbox", fake_base_sandbox)

    session = wandb_sandbox.Session()
    result = session.sandbox(command="sleep", future_option={"enabled": True})

    assert result is sandbox
    assert calls == [
        (session, {"command": "sleep", "future_option": {"enabled": True}})
    ]


def test_sandbox_classmethod_session_uses_wandb_session_wrapper() -> None:
    session = wandb_sandbox.Sandbox.session()

    assert isinstance(session, wandb_sandbox.Session)
