import pytest
import wandb
from wandb.proto.wandb_api_pb2 import AuthenticateResponse
from wandb.sdk.lib import identity
from wandb.sdk.lib.service.service_connection import WandbApiFailedError

_RESPONSE = AuthenticateResponse(
    default_entity="my-entity",
    username="my-user",
    email="me@example.com",
    teams=["team1"],
    flags_json='{"code_saving_enabled": true}',
)


@pytest.fixture
def authenticate_calls(monkeypatch: pytest.MonkeyPatch) -> list[Exception | None]:
    """Stub ServiceApi.authenticate with a scripted sequence of outcomes.

    Prepend exceptions to raise; when empty, returns a valid response.
    The list mutates in place, so tests can inspect and reprogram it.
    """
    script: list[Exception | None] = []

    def fake_authenticate(self, *args, **kwargs):
        if script:
            outcome = script.pop(0)
            if outcome is not None:
                raise outcome
        return _RESPONSE

    monkeypatch.setattr(
        "wandb.apis.public.service_api.ServiceApi.authenticate",
        fake_authenticate,
    )
    return script


def test_resolves_identity(authenticate_calls):
    session_identity = identity.SessionIdentity(wandb.Settings())

    resolved = session_identity.identity

    assert resolved is not None
    assert resolved.default_entity == "my-entity"
    assert resolved.username == "my-user"
    assert resolved.email == "me@example.com"
    assert resolved.teams == ("team1",)
    assert resolved.flags == {"code_saving_enabled": True}


def test_caches_successful_resolution(authenticate_calls):
    session_identity = identity.SessionIdentity(wandb.Settings())

    first = session_identity.identity
    # Any further call would raise, proving the cached result is used.
    authenticate_calls.append(AssertionError("must not be called again"))
    second = session_identity.identity

    assert first is second


def test_retries_after_failure(authenticate_calls):
    authenticate_calls.append(WandbApiFailedError("transient failure"))
    session_identity = identity.SessionIdentity(wandb.Settings())

    assert session_identity.identity is None

    # The failure is not cached: the next access tries again.
    resolved = session_identity.identity
    assert resolved is not None
    assert resolved.username == "my-user"


@pytest.mark.parametrize("settings", [{"mode": "offline"}, {"x_disable_viewer": True}])
def test_does_not_resolve_when_disabled(authenticate_calls, settings):
    authenticate_calls.append(AssertionError("must not be called"))
    session_identity = identity.SessionIdentity(wandb.Settings(**settings))

    assert session_identity.identity is None
