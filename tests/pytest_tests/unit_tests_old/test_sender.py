import os
import queue
import threading

import pytest
import wandb
import wandb.proto.wandb_internal_pb2 as pb
from wandb.sdk.lib.printer import INFO

from tests.pytest_tests.unit_tests_old import utils


def test_send_status_request_stopped(mock_server, backend_interface):
    mock_server.ctx["stopped"] = True

    with backend_interface() as interface:
        handle = interface.deliver_stop_status()
        result = handle.wait(timeout=5)
        stop_status = result.response.stop_status_response
        assert result is not None
        assert stop_status.run_should_stop


def test_parallel_requests(mock_server, backend_interface):
    mock_server.ctx["stopped"] = True
    work_queue = queue.Queue()

    with backend_interface() as interface:

        def send_sync_request(i):
            work_queue.get()
            if i % 3 == 0:
                handle = interface.deliver_stop_status()
                result = handle.wait(timeout=5)
                stop_status = result.response.stop_status_response
                assert stop_status is not None
                assert stop_status.run_should_stop
            elif i % 3 == 2:
                handle = interface.deliver_get_summary()
                result = handle.wait(timeout=5)
                summary = result.response.get_summary_response
                assert summary is not None
                assert hasattr(summary, "item")
            work_queue.task_done()

        for i in range(10):
            work_queue.put(None)
            t = threading.Thread(target=send_sync_request, args=(i,))
            t.daemon = True
            t.start()

        work_queue.join()


def test_send_status_request_network(mock_server, backend_interface):
    mock_server.ctx["rate_limited_times"] = 3

    with backend_interface() as interface:
        interface.publish_files({"files": [("test.txt", "live")]})

        handle = interface.deliver_network_status()
        result = handle.wait(timeout=5)
        assert result is not None
        network = result.response.network_status_response
        assert len(network.network_responses) > 0
        assert network.network_responses[0].http_status_code == 429


def test_resume_success(mocked_run, test_settings, mock_server, backend_interface):
    test_settings.update(resume="allow", source=wandb.sdk.wandb_settings.Source.INIT)
    mock_server.ctx["resume"] = True
    with backend_interface(initial_run=False) as interface:
        handle = interface.deliver_run(mocked_run)
        result = handle.wait(timeout=5)
        run_result = result.run_result
        assert run_result.HasField("error") is False
        assert run_result.run.starting_step == 16


def test_resume_error_never(mocked_run, test_settings, mock_server, backend_interface):
    test_settings.update(resume="never", source=wandb.sdk.wandb_settings.Source.INIT)
    mock_server.ctx["resume"] = True
    with backend_interface(initial_run=False) as interface:
        handle = interface.deliver_run(mocked_run)
        result = handle.wait(timeout=5)
        run_result = result.run_result
        assert run_result.HasField("error")
        assert run_result.error.code == pb.ErrorInfo.ErrorCode.USAGE


def test_resume_error_must(mocked_run, test_settings, mock_server, backend_interface):
    test_settings.update(resume="must", source=wandb.sdk.wandb_settings.Source.INIT)
    mock_server.ctx["resume"] = False
    with backend_interface(initial_run=False) as interface:
        handle = interface.deliver_run(mocked_run)
        result = handle.wait(timeout=5)
        run_result = result.run_result
        assert run_result.HasField("error")
        assert run_result.error.code == pb.ErrorInfo.ErrorCode.USAGE


def test_output(mocked_run, mock_server, backend_interface):
    with backend_interface() as interface:
        for i in range(100):
            interface.publish_output("stdout", "\rSome recurring line")
        interface.publish_output("stdout", "\rFinal line baby\n")

    print("DUDE!", mock_server.ctx)
    stream = utils.first_filestream(mock_server.ctx)
    assert "Final line baby" in stream["files"]["output.log"]["content"][0]


def test_sync_spell_run(mocked_run, mock_server, backend_interface, parse_ctx):
    try:
        os.environ["SPELL_RUN_URL"] = "https://spell.run/foo"
        with backend_interface() as interface:
            pass
        print("CTX", mock_server.ctx)
        ctx = parse_ctx(mock_server.ctx)
        assert ctx.config["_wandb"]["value"]["spell_url"] == "https://spell.run/foo"
        # Check that we pinged spells API
        assert mock_server.ctx["spell_data"] == {
            "access_token": None,
            "url": "{}/mock_server_entity/test/runs/{}".format(
                mocked_run._settings.base_url, mocked_run.id
            ),
        }
    finally:
        del os.environ["SPELL_RUN_URL"]
