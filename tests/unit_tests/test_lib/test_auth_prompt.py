from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from wandb.errors import links, term
from wandb.sdk.lib.wbauth import host_url, prompt, saas, wbnetrc

from tests.fixtures.emulated_terminal import EmulatedTerminal


@pytest.fixture(autouse=True)
def mock_write_netrc(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Mock write_netrc_auth for all tests."""
    write_netrc = MagicMock()
    monkeypatch.setattr(wbnetrc, "write_netrc_auth", write_netrc)
    return write_netrc


def test_authorize_url_uses_app_url():
    result = prompt._authorize_url(
        host_url.HostUrl("https://my-api", app_url="https://my-ui"),
        signup=False,
        referrer="",
    )

    assert result == "https://my-ui/authorize"


def test_timeout(emulated_terminal: EmulatedTerminal):
    _ = emulated_terminal  # select nothing, allow a timeout

    with pytest.raises(TimeoutError):
        prompt.prompt_and_save_api_key(host="https://test-host", input_timeout=1)


def test_not_a_terminal():
    with pytest.raises(term.NotATerminalError):
        prompt.prompt_and_save_api_key(host="https://test-host")


def test_no_offline(emulated_terminal: EmulatedTerminal):
    _ = emulated_terminal  # select nothing, allow a timeout

    with pytest.raises(TimeoutError):
        prompt.prompt_and_save_api_key(
            host="https://test-host",
            no_offline=True,
            input_timeout=1,
        )

    assert emulated_terminal.read_stderr() == [
        "wandb: (1) Create a W&B account",
        "wandb: (2) Use an existing W&B account",
        "wandb: Enter your choice:",
    ]


def test_no_create(emulated_terminal: EmulatedTerminal):
    _ = emulated_terminal  # select nothing, allow a timeout

    with pytest.raises(TimeoutError):
        prompt.prompt_and_save_api_key(
            host="https://test-host",
            no_create=True,
            input_timeout=1,
        )

    assert emulated_terminal.read_stderr() == [
        "wandb: (1) Use an existing W&B account",
        "wandb: (2) Don't visualize my results",
        "wandb: Enter your choice:",
    ]


def test_writes_to_netrc(
    emulated_terminal: EmulatedTerminal,
    mock_write_netrc: MagicMock,
):
    emulated_terminal.queue_input("1")  # select "create a new account"
    emulated_terminal.queue_input("test" * 10)  # input a fake API key
    prompt.prompt_and_save_api_key(host="https://test-host")

    mock_write_netrc.assert_called_once_with(
        host="https://test-host",
        api_key="test" * 10,
    )


def test_does_not_write_to_netrc_if_no_key(
    emulated_terminal: EmulatedTerminal,
    mock_write_netrc: MagicMock,
):
    emulated_terminal.queue_input("3")  # select offline mode
    prompt.prompt_and_save_api_key(host="https://test-host")

    mock_write_netrc.assert_not_called()


@pytest.mark.parametrize("referrer", ("", "test"))
def test_choice_new(referrer: str, emulated_terminal: EmulatedTerminal):
    emulated_terminal.queue_input("1")  # select "create a new account"
    emulated_terminal.queue_input("test" * 10)  # input a fake API key
    result = prompt.prompt_and_save_api_key(
        host="https://test-host",
        referrer=referrer,
    )

    if referrer:
        expected_auth_url = f"https://test-host/authorize?signup=true&ref={referrer}"
    else:
        expected_auth_url = "https://test-host/authorize?signup=true"

    assert result == "test" * 10
    assert emulated_terminal.read_stderr() == [
        "wandb: (1) Create a W&B account",
        "wandb: (2) Use an existing W&B account",
        "wandb: (3) Don't visualize my results",
        "wandb: Enter your choice: 1",
        "wandb: You chose 'Create a W&B account'",
        f"wandb: Create an account here: {expected_auth_url}",
        "wandb: After creating your account, create a new API key and store it securely.",
        "wandb: Paste your API key and hit enter:",
    ]


def test_choice_new_invalid(emulated_terminal: EmulatedTerminal):
    emulated_terminal.queue_input("1")  # select "create a new account"
    emulated_terminal.queue_input("")  # press enter without typing anything
    emulated_terminal.queue_input("2")  # select "create an existing account"
    emulated_terminal.queue_input("test" * 10)  # enter a valid key
    result = prompt.prompt_and_save_api_key(host="https://test-host", input_timeout=1)

    assert result == "test" * 10
    assert (
        "wandb: ERROR Invalid API key: API key is empty."
        in emulated_terminal.read_stderr()
    )


@pytest.mark.parametrize("referrer", (None, "test-referrer"))
@pytest.mark.parametrize("is_wandb_domain", (False, True))
def test_choice_existing(
    referrer: str,
    is_wandb_domain: bool,
    emulated_terminal: EmulatedTerminal,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(
        saas,
        "is_wandb_domain",
        lambda *args: is_wandb_domain,
    )

    emulated_terminal.queue_input("2")  # select "use an existing account"
    emulated_terminal.queue_input("test" * 10)  # input a fake API key
    result = prompt.prompt_and_save_api_key(
        host="https://test-host",
        referrer=referrer,
    )

    if referrer:
        expected_auth_url = f"https://test-host/authorize?ref={referrer}"
    else:
        expected_auth_url = "https://test-host/authorize"

    if is_wandb_domain:
        help_url = links.url_registry.url("wandb-server")
        maybe_local_server_hint = [
            # Lines are wrapped at 80 characters in the test terminal.
            "wandb: Logging into https://test-host."
            + " (Learn how to deploy a W&B server locally",
            f": {help_url})",
        ]
    else:
        maybe_local_server_hint = []

    assert result == "test" * 10
    assert emulated_terminal.read_stderr() == [
        "wandb: (1) Create a W&B account",
        "wandb: (2) Use an existing W&B account",
        "wandb: (3) Don't visualize my results",
        "wandb: Enter your choice: 2",
        "wandb: You chose 'Use an existing W&B account'",
    ] + maybe_local_server_hint + [
        f"wandb: Create a new API key at: {expected_auth_url}",
        "wandb: Store your API key securely and do not share it.",
        "wandb: Paste your API key and hit enter:",
    ]


def test_choice_existing_invalid(emulated_terminal: EmulatedTerminal):
    emulated_terminal.queue_input("2")  # select "use an existing account"
    emulated_terminal.queue_input("")  # press enter without typing anything
    emulated_terminal.queue_input("1")  # select "create a new account"
    emulated_terminal.queue_input("test" * 10)  # enter a valid key
    result = prompt.prompt_and_save_api_key(host="https://test-host", input_timeout=1)

    assert result == "test" * 10
    assert (
        "wandb: ERROR Invalid API key: API key is empty."
        in emulated_terminal.read_stderr()
    )


def test_choice_offline(emulated_terminal: EmulatedTerminal):
    emulated_terminal.queue_input("3")  # select offline mode in prompt
    result = prompt.prompt_and_save_api_key(host="https://test-host")

    assert result is None
