import pytest
from wandb.errors import links, term
from wandb.sdk.lib.auth import anon, prompt, saas

from tests.fixtures.emulated_terminal import EmulatedTerminal


def test_authorize_url_uses_app_url():
    result = prompt._authorize_url(
        "https://api.wandb.ai",
        signup=False,
        referrer="",
    )

    # There's special logic to map several API URL formats to "app" URLs.
    # This just tests that we're not using the API URL directly.
    assert result == "https://wandb.ai/authorize"


def test_timeout(emulated_terminal: EmulatedTerminal):
    _ = emulated_terminal  # select nothing, allow a timeout

    with pytest.raises(TimeoutError):
        prompt.prompt_api_key(host="https://test-host", input_timeout=1)


def test_not_a_terminal():
    with pytest.raises(term.NotATerminalError):
        prompt.prompt_api_key(host="https://test-host")


def test_no_anonymous(emulated_terminal: EmulatedTerminal):
    _ = emulated_terminal  # select nothing, allow a timeout

    with pytest.raises(TimeoutError):
        prompt.prompt_api_key(
            host="https://test-host",
            no_anonymous=True,
            input_timeout=1,
        )

    assert emulated_terminal.read_stderr() == [
        "wandb: (1) Create a W&B account",
        "wandb: (2) Use an existing W&B account",
        "wandb: (3) Don't visualize my results",
        "wandb: Enter your choice:",
    ]


def test_no_offline(emulated_terminal: EmulatedTerminal):
    _ = emulated_terminal  # select nothing, allow a timeout

    with pytest.raises(TimeoutError):
        prompt.prompt_api_key(
            host="https://test-host",
            no_offline=True,
            input_timeout=1,
        )

    assert emulated_terminal.read_stderr() == [
        "wandb: (1) Private W&B dashboard, no account required",
        "wandb: (2) Create a W&B account",
        "wandb: (3) Use an existing W&B account",
        "wandb: Enter your choice:",
    ]


def test_no_create(emulated_terminal: EmulatedTerminal):
    _ = emulated_terminal  # select nothing, allow a timeout

    with pytest.raises(TimeoutError):
        prompt.prompt_api_key(
            host="https://test-host",
            no_create=True,
            input_timeout=1,
        )

    assert emulated_terminal.read_stderr() == [
        "wandb: (1) Private W&B dashboard, no account required",
        "wandb: (2) Use an existing W&B account",
        "wandb: (3) Don't visualize my results",
        "wandb: Enter your choice:",
    ]


def test_choice_anonymous(
    emulated_terminal: EmulatedTerminal,
    monkeypatch: pytest.MonkeyPatch,
):
    fake_key = "ANONYMOOSE" * 4
    monkeypatch.setattr(
        anon,
        "make_anonymous_api_key",
        lambda *args, **kwargs: fake_key,
    )

    emulated_terminal.queue_input("1")  # select anonymous mode in prompt
    result = prompt.prompt_api_key(host="https://test-host")

    assert result == fake_key


def test_choice_anonymous_error_retries(
    emulated_terminal: EmulatedTerminal,
    monkeypatch: pytest.MonkeyPatch,
):
    def raise_error(*args, **kwargs):
        raise Exception("Test error")

    monkeypatch.setattr(anon, "make_anonymous_api_key", raise_error)

    emulated_terminal.queue_input("1")  # select anonymous mode in prompt
    emulated_terminal.queue_input("3")  # select "use an existing account"
    emulated_terminal.queue_input("test" * 10)  # input a fake API key
    result = prompt.prompt_api_key(host="https://test-host")

    assert result == "test" * 10
    assert (
        "wandb: ERROR Error creating an anonymous API key: Test error"
        in emulated_terminal.read_stderr()
    )


@pytest.mark.parametrize("referrer", ("", "test"))
def test_choice_new(referrer: str, emulated_terminal: EmulatedTerminal):
    emulated_terminal.queue_input("2")  # select "create a new account"
    emulated_terminal.queue_input("test" * 10)  # input a fake API key
    result = prompt.prompt_api_key(
        host="https://test-host",
        referrer=referrer,
    )

    if referrer:
        expected_auth_url = f"https://test-host/authorize?signup=true&ref={referrer}"
    else:
        expected_auth_url = "https://test-host/authorize?signup=true"

    assert result == "test" * 10
    assert emulated_terminal.read_stderr() == [
        "wandb: (1) Private W&B dashboard, no account required",
        "wandb: (2) Create a W&B account",
        "wandb: (3) Use an existing W&B account",
        "wandb: (4) Don't visualize my results",
        "wandb: Enter your choice: 2",
        "wandb: You chose 'Create a W&B account'",
        f"wandb: Create an account here: {expected_auth_url}",
        "wandb: Paste an API key from your profile and hit enter:",
    ]


def test_choice_new_invalid(emulated_terminal: EmulatedTerminal):
    emulated_terminal.queue_input("2")  # select "create a new account"
    emulated_terminal.queue_input("")  # press enter without typing anything
    emulated_terminal.queue_input("3")  # select "create an existing account"
    emulated_terminal.queue_input("test" * 10)  # enter a valid key
    result = prompt.prompt_api_key(host="https://test-host", input_timeout=1)

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

    emulated_terminal.queue_input("3")  # select "use an existing account"
    emulated_terminal.queue_input("test" * 10)  # input a fake API key
    result = prompt.prompt_api_key(
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
        "wandb: (1) Private W&B dashboard, no account required",
        "wandb: (2) Create a W&B account",
        "wandb: (3) Use an existing W&B account",
        "wandb: (4) Don't visualize my results",
        "wandb: Enter your choice: 3",
        "wandb: You chose 'Use an existing W&B account'",
    ] + maybe_local_server_hint + [
        f"wandb: Find your API key here: {expected_auth_url}",
        "wandb: Paste an API key from your profile and hit enter:",
    ]


def test_choice_existing_invalid(emulated_terminal: EmulatedTerminal):
    emulated_terminal.queue_input("3")  # select "use an existing account"
    emulated_terminal.queue_input("")  # press enter without typing anything
    emulated_terminal.queue_input("2")  # select "create a new account"
    emulated_terminal.queue_input("test" * 10)  # enter a valid key
    result = prompt.prompt_api_key(host="https://test-host", input_timeout=1)

    assert result == "test" * 10
    assert (
        "wandb: ERROR Invalid API key: API key is empty."
        in emulated_terminal.read_stderr()
    )


def test_choice_offline(emulated_terminal: EmulatedTerminal):
    emulated_terminal.queue_input("4")  # select offline mode in prompt
    result = prompt.prompt_api_key(host="https://test-host")

    assert result is None
