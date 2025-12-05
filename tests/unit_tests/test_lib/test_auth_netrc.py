import pathlib
import textwrap

import pytest
from wandb.sdk.lib.wbauth import wbnetrc

from tests.fixtures.mock_wandb_log import MockWandbLog


@pytest.fixture
def fake_netrc_path(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
) -> pathlib.Path:
    path = tmp_path / "test-netrc"
    monkeypatch.setenv("NETRC", str(path))
    return path


def test_read(fake_netrc_path: pathlib.Path):
    key = "test" * 10
    fake_netrc_path.write_text(f"machine test login user password {key}")

    result = wbnetrc.read_netrc_auth(host="https://test")

    assert result == key


def test_read_host_not_found(fake_netrc_path: pathlib.Path):
    fake_netrc_path.write_text("machine test login user password pass")

    result = wbnetrc.read_netrc_auth(host="https://other")

    assert result is None


def test_read_file_not_found(fake_netrc_path: pathlib.Path):
    _ = fake_netrc_path  # don't create the file

    result = wbnetrc.read_netrc_auth(host="https://test-host")

    assert result is None


def test_read_parse_error(
    fake_netrc_path: pathlib.Path,
    mock_wandb_log: MockWandbLog,
):
    fake_netrc_path.write_text("invalid")

    result = wbnetrc.read_netrc_auth(host="https://test-host")

    assert result is None
    mock_wandb_log.assert_warned("Failed to read netrc file")


def test_read_unreadable(
    fake_netrc_path: pathlib.Path,
    mock_wandb_log: MockWandbLog,
):
    fake_netrc_path.mkdir()

    result = wbnetrc.read_netrc_auth(host="https://test-host")

    assert result is None
    mock_wandb_log.assert_warned("Failed to read netrc file")


def test_write(fake_netrc_path: pathlib.Path):
    fake_netrc_path.write_text(
        textwrap.dedent("""\
            machine other-host-1
              login user-1
              password pass-1
            machine test-host:123
              login user
              password pass
            machine other-host-2
              login user-2
              password pass-2
        """)
    )

    wbnetrc.write_netrc_auth(host="https://test-host:123/", api_key="new-pass")

    assert fake_netrc_path.read_text() == textwrap.dedent("""\
            machine other-host-1
              login user-1
              password pass-1
            machine other-host-2
              login user-2
              password pass-2
            machine test-host:123
              login user
              password new-pass
        """)


def test_write_shell_quoting(fake_netrc_path: pathlib.Path):
    wbnetrc.write_netrc_auth(
        host="https://test-host",
        # Try to inject .netrc syntax into the API key.
        api_key="pass machine attacker password actual-api-key",
    )

    assert fake_netrc_path.read_text() == textwrap.dedent("""\
            machine test-host
              login user
              password 'pass machine attacker password actual-api-key'
        """)


def test_write_error_reading(fake_netrc_path: pathlib.Path):
    # Create a directory at the .netrc file path.
    fake_netrc_path.mkdir()

    with pytest.raises(wbnetrc.WriteNetrcError, match="Unable to read"):
        wbnetrc.write_netrc_auth(host="https://test-host", api_key="pass")


def test_write_error_writing(
    fake_netrc_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
):
    def raise_os_error():
        raise OSError("Test error")

    # One way to test is to create a file with mode 0o400 (read but not write),
    # but this assumes the test isn't running as root. A test like this doesn't
    # raise an error in CI, so we monkeypatch the write function instead.
    _ = fake_netrc_path
    monkeypatch.setattr(wbnetrc, "_write_text", lambda *args: raise_os_error())

    with pytest.raises(wbnetrc.WriteNetrcError, match="Unable to write"):
        wbnetrc.write_netrc_auth(host="https://test-host", api_key="pass")
