import os
import signal
from unittest import mock

import pytest
from wandb import wandb_agent


class _DummyPopen:
    def __init__(self, *args, **kwargs):
        self.stdin = mock.Mock()
        self.sent = []

    def send_signal(self, signum):
        self.sent.append(signum)

    def kill(self):
        self.sent.append("kill")


def _capture_handlers(monkeypatch, valid_signals):
    installed = {}

    def fake_valid_signals():
        return valid_signals

    def fake_signal(signum, handler):
        installed[signum] = handler
        return handler

    monkeypatch.setattr(signal, "valid_signals", fake_valid_signals, raising=False)
    monkeypatch.setattr(signal, "signal", fake_signal)
    return installed


@pytest.mark.skipif(os.name == "nt", reason="POSIX-only handler coverage")
def test_agent_process_installs_handlers_for_all_valid_signals(monkeypatch):
    valid = {signal.SIGINT, signal.SIGTERM}
    if hasattr(signal, "SIGKILL"):
        valid.add(signal.SIGKILL)
    handlers = _capture_handlers(monkeypatch, valid)
    original_map = {}

    def fake_getsignal(signum):
        original_map[signum] = f"orig-{signum}"
        return original_map[signum]

    monkeypatch.setattr(signal, "getsignal", fake_getsignal)
    monkeypatch.setattr(wandb_agent.subprocess, "Popen", _DummyPopen)
    monkeypatch.setattr(wandb_agent.platform, "system", lambda: "Linux")

    proc = wandb_agent.AgentProcess(
        env={},
        command=["python", "-c", "0"],
        forward_signals=True,
    )

    if hasattr(signal, "SIGKILL"):
        assert signal.SIGKILL not in handlers
    assert set(handlers) == {signal.SIGINT, signal.SIGTERM}
    for signum in handlers:
        assert proc._original_handlers[signum] == f"orig-{signum}"


@pytest.mark.skipif(os.name == "nt", reason="POSIX-only forwarding path")
def test_agent_process_forwards_command_signal_on_posix(monkeypatch):
    handlers = _capture_handlers(monkeypatch, {signal.SIGTERM})
    dummy_holder = {}

    def fake_getsignal(signum):
        return None

    def fake_popen(*args, **kwargs):
        dummy = _DummyPopen()
        dummy_holder["popen"] = dummy
        return dummy

    monkeypatch.setattr(signal, "getsignal", fake_getsignal)
    monkeypatch.setattr(wandb_agent.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(wandb_agent.platform, "system", lambda: "Linux")

    wandb_agent.AgentProcess(
        env={},
        command=["python", "-c", "0"],
        forward_signals=True,
    )

    handler = handlers[signal.SIGTERM]
    # _forward_signal raises ShutdownSignal after forwarding SIGTERM so
    # Agent.run's cleanup cascade runs; assert forwarding happened first.
    with pytest.raises(wandb_agent.ShutdownSignal) as excinfo:
        handler(signal.SIGTERM, None)
    assert excinfo.value.signum == signal.SIGTERM
    assert dummy_holder["popen"].sent == [signal.SIGTERM]


def test_agent_process_forwards_signals_on_windows(monkeypatch):
    handlers = _capture_handlers(monkeypatch, {signal.SIGTERM})
    dummy_holder = {}

    def fake_getsignal(signum):
        handler = mock.Mock()
        dummy_holder.setdefault("originals", {})[signum] = handler
        return handler

    def fake_popen(*args, **kwargs):
        dummy = _DummyPopen()
        dummy_holder["popen"] = dummy
        return dummy

    monkeypatch.setattr(signal, "getsignal", fake_getsignal)
    monkeypatch.setattr(wandb_agent.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(
        wandb_agent.subprocess, "CREATE_NEW_PROCESS_GROUP", 0, raising=False
    )
    monkeypatch.setattr(wandb_agent.platform, "system", lambda: "Windows")
    monkeypatch.setattr(signal, "CTRL_BREAK_EVENT", 4242, raising=False)

    wandb_agent.AgentProcess(
        env={},
        command=["python", "-c", "0"],
        forward_signals=True,
    )

    handler = handlers[signal.SIGTERM]
    handler(signal.SIGTERM, None)
    dummy = dummy_holder["popen"]
    assert dummy.sent == [4242]
    original = dummy_holder["originals"][signal.SIGTERM]
    original.assert_called_once_with(signal.SIGTERM, None)


@pytest.mark.skipif(os.name == "nt", reason="POSIX-only function process path")
def test_agent_process_forwards_to_function_process(monkeypatch):
    handlers = _capture_handlers(monkeypatch, {signal.SIGTERM})

    def fake_getsignal(signum):
        return None

    monkeypatch.setattr(signal, "getsignal", fake_getsignal)
    monkeypatch.setattr(wandb_agent.subprocess, "Popen", _DummyPopen)
    monkeypatch.setattr(wandb_agent.platform, "system", lambda: "Linux")

    proc = wandb_agent.AgentProcess(
        env={},
        command=["python", "-c", "0"],
        forward_signals=True,
    )
    mock_proc = mock.Mock()
    proc._proc = mock_proc
    proc._popen = None

    handler = handlers[signal.SIGTERM]
    # _forward_signal raises ShutdownSignal after forwarding SIGTERM so
    # Agent.run's cleanup cascade runs; assert forwarding happened first.
    with pytest.raises(wandb_agent.ShutdownSignal) as excinfo:
        handler(signal.SIGTERM, None)
    assert excinfo.value.signum == signal.SIGTERM
    mock_proc.send_signal.assert_called_once_with(signal.SIGTERM)


@pytest.mark.skipif(os.name == "nt", reason="POSIX-only SIGKILL path")
def test_agent_process_kills_function_process_on_sigkill(monkeypatch):
    handlers = _capture_handlers(monkeypatch, {signal.SIGTERM})

    def fake_getsignal(signum):
        return None

    monkeypatch.setattr(signal, "getsignal", fake_getsignal)
    monkeypatch.setattr(wandb_agent.subprocess, "Popen", _DummyPopen)
    monkeypatch.setattr(wandb_agent.platform, "system", lambda: "Linux")

    proc = wandb_agent.AgentProcess(
        env={},
        command=["python", "-c", "0"],
        forward_signals=True,
    )
    mock_proc = mock.Mock()
    proc._proc = mock_proc
    proc._popen = None

    handler = handlers[signal.SIGTERM]
    handler(signal.SIGKILL, None)
    mock_proc.kill.assert_called_once()


def test_agent_run_exits_without_further_heartbeat_on_shutdown_signal(monkeypatch):
    """ShutdownSignal raised inside the loop must stop the heartbeat and
    run the wait/terminate cleanup cascade on active run processes."""
    api = mock.Mock()
    api.sweep.return_value = {"config": ""}
    api.register_agent.return_value = {"id": "agent-1"}
    api.agent_heartbeat.side_effect = wandb_agent.ShutdownSignal(signal.SIGTERM)

    monkeypatch.setattr(wandb_agent.util, "read_many_from_queue", lambda *a, **kw: [])

    agent = wandb_agent.Agent(api=api, queue=mock.Mock(), sweep_id="sweep-1")

    run_process = mock.Mock()
    run_process.poll.return_value = None
    agent._run_processes["run-1"] = run_process

    # ShutdownSignal must be caught inside Agent.run, not escape.
    agent.run()

    assert api.agent_heartbeat.call_count == 1
    run_process.wait.assert_called()
    run_process.terminate.assert_called()


def test_agent_run_second_shutdown_signal_escalates_to_terminate(monkeypatch):
    """A second ShutdownSignal during Tier 1 wait() must escalate to Tier 2:
    terminate() the run process, then wait() again."""
    api = mock.Mock()
    api.sweep.return_value = {"config": ""}
    api.register_agent.return_value = {"id": "agent-1"}
    api.agent_heartbeat.side_effect = wandb_agent.ShutdownSignal(signal.SIGTERM)

    monkeypatch.setattr(wandb_agent.util, "read_many_from_queue", lambda *a, **kw: [])

    agent = wandb_agent.Agent(api=api, queue=mock.Mock(), sweep_id="sweep-1")

    run_process = mock.Mock()
    run_process.poll.return_value = None
    # Tier 1's wait() is interrupted by a second signal; Tier 2's wait() (after
    # terminate()) returns normally.
    run_process.wait.side_effect = [
        wandb_agent.ShutdownSignal(signal.SIGTERM),
        None,
    ]
    agent._run_processes["run-1"] = run_process

    agent.run()

    assert run_process.wait.call_count == 2
    run_process.terminate.assert_called_once()
    run_process.kill.assert_not_called()


def test_agent_run_skips_tier2_when_runs_already_exited(monkeypatch):
    """When Tier 1's wait() returns cleanly (child exited gracefully on the
    forwarded signal), the finally block must skip Tier-2 messaging and
    operations rather than misleadingly claim it is terminating runs."""
    api = mock.Mock()
    api.sweep.return_value = {"config": ""}
    api.register_agent.return_value = {"id": "agent-1"}
    api.agent_heartbeat.side_effect = wandb_agent.ShutdownSignal(signal.SIGTERM)

    monkeypatch.setattr(wandb_agent.util, "read_many_from_queue", lambda *a, **kw: [])

    agent = wandb_agent.Agent(api=api, queue=mock.Mock(), sweep_id="sweep-1")

    run_process = mock.Mock()
    # Alive during the main-loop poll, exited by the time the finally
    # block probes for still-running processes.
    run_process.poll.side_effect = [None, 0]
    agent._run_processes["run-1"] = run_process

    agent.run()

    run_process.wait.assert_called()  # Tier 1 ran
    run_process.terminate.assert_not_called()  # Tier 2 skipped
    run_process.kill.assert_not_called()  # Tier 3 not reached


def test_agent_run_third_shutdown_signal_escalates_to_kill(monkeypatch):
    """A third ShutdownSignal (interrupting Tier 2's wait()) must escalate to
    Tier 3: kill() the run process."""
    api = mock.Mock()
    api.sweep.return_value = {"config": ""}
    api.register_agent.return_value = {"id": "agent-1"}
    api.agent_heartbeat.side_effect = wandb_agent.ShutdownSignal(signal.SIGTERM)

    monkeypatch.setattr(wandb_agent.util, "read_many_from_queue", lambda *a, **kw: [])

    agent = wandb_agent.Agent(api=api, queue=mock.Mock(), sweep_id="sweep-1")

    run_process = mock.Mock()
    run_process.poll.return_value = None
    # Both Tier 1's wait() and Tier 2's wait() are interrupted by signals.
    run_process.wait.side_effect = [
        wandb_agent.ShutdownSignal(signal.SIGTERM),
        wandb_agent.ShutdownSignal(signal.SIGTERM),
    ]
    agent._run_processes["run-1"] = run_process

    agent.run()

    run_process.terminate.assert_called_once()
    run_process.kill.assert_called_once()


@pytest.mark.skipif(os.name == "nt", reason="POSIX-only signal registration path")
def test_agent_process_continues_when_signal_registration_fails(monkeypatch):
    bad_signal = 9999
    valid = {signal.SIGTERM, bad_signal}
    handlers = {}

    def fake_getsignal(signum):
        return None

    def fake_signal(signum, handler):
        if signum == bad_signal:
            raise ValueError("unsupported")
        handlers[signum] = handler
        return handler

    monkeypatch.setattr(signal, "valid_signals", lambda: valid)
    monkeypatch.setattr(signal, "signal", fake_signal)
    monkeypatch.setattr(signal, "getsignal", fake_getsignal)
    monkeypatch.setattr(wandb_agent.subprocess, "Popen", _DummyPopen)
    monkeypatch.setattr(wandb_agent.platform, "system", lambda: "Linux")

    proc = wandb_agent.AgentProcess(
        env={},
        command=["python", "-c", "0"],
        forward_signals=True,
    )

    assert bad_signal not in handlers
    assert bad_signal in proc._original_handlers
