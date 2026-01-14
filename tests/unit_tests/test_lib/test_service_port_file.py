from unittest import mock

import pytest
from wandb.sdk.lib.service import ipc_support, service_port_file, service_token


@pytest.fixture(autouse=True)
def make_sleep_instant(monkeypatch):
    test_time = 0

    def fake_sleep(seconds: float) -> None:
        nonlocal test_time
        test_time += seconds

    monkeypatch.setattr(service_port_file, "_MONOTONIC", lambda: test_time)
    monkeypatch.setattr(service_port_file, "_SLEEP", fake_sleep)


@pytest.fixture
def running_process():
    proc = mock.Mock()
    proc.poll.return_value = None
    return proc


@pytest.fixture
def finished_process():
    proc = mock.Mock()
    proc.poll.return_value = 1
    return proc


@pytest.mark.skipif(
    not ipc_support.SUPPORTS_UNIX,
    reason="AF_UNIX sockets not supported",
)
def test_reads_unix_token(tmp_path, running_process):
    port_file = tmp_path / "ports"
    port_file.write_text("unix=/some/path\nsock=123\nEOF")

    token = service_port_file.poll_for_token(
        port_file,
        running_process,
        timeout=1,
    )

    assert isinstance(token, service_token.UnixServiceToken)
    assert token._path == "/some/path"


def test_ignores_unix_token_if_not_supported(
    monkeypatch,
    tmp_path,
    running_process,
):
    port_file = tmp_path / "ports"
    port_file.write_text("unix=/some/path\nsock=123\nEOF")
    monkeypatch.setattr(ipc_support, "SUPPORTS_UNIX", False)

    token = service_port_file.poll_for_token(
        port_file,
        running_process,
        timeout=1,
    )

    assert isinstance(token, service_token.TCPServiceToken)
    assert token._port == 123


def test_reads_tcp_token(tmp_path, running_process):
    port_file = tmp_path / "ports"
    port_file.write_text("sock=123\nEOF")

    token = service_port_file.poll_for_token(
        port_file,
        running_process,
        timeout=1,
    )

    assert isinstance(token, service_token.TCPServiceToken)
    assert token._port == 123


def test_fails_if_process_dies(tmp_path, finished_process):
    with pytest.raises(
        service_port_file.ServicePollForTokenError,
        match="wandb-core exited with code",
    ):
        service_port_file.poll_for_token(
            tmp_path / "ports",
            finished_process,
            timeout=30,
        )


def test_fails_if_no_known_connection_method(tmp_path, running_process):
    port_file = tmp_path / "ports"
    port_file.write_text("EOF")

    with pytest.raises(
        service_port_file.ServicePollForTokenError,
        match="No known connection method",
    ):
        service_port_file.poll_for_token(port_file, running_process, timeout=1)


def test_times_out_if_file_never_created(tmp_path, running_process):
    with pytest.raises(
        service_port_file.ServicePollForTokenError,
        match="Failed to read port info after 30 seconds.",
    ):
        service_port_file.poll_for_token(
            tmp_path / "ports",
            running_process,
            timeout=30,
        )


def test_times_out_if_file_incomplete(tmp_path, running_process):
    port_file = tmp_path / "ports"
    port_file.write_text("sock=123\n")

    with pytest.raises(
        service_port_file.ServicePollForTokenError,
        match="Failed to read port info after 30 seconds.",
    ):
        service_port_file.poll_for_token(
            port_file,
            running_process,
            timeout=30,
        )
