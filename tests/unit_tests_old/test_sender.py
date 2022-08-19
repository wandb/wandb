import os
import queue
import threading

import pytest
import wandb
from wandb.sdk.lib.printer import INFO

from tests.unit_tests_old import utils


def test_send_status_request_stopped(mock_server, backend_interface):
    mock_server.ctx["stopped"] = True

    with backend_interface() as interface:
        status_resp = interface.communicate_stop_status()
        assert status_resp is not None
        assert status_resp.run_should_stop


def test_parallel_requests(mock_server, backend_interface):
    mock_server.ctx["stopped"] = True
    work_queue = queue.Queue()

    with backend_interface() as interface:

        def send_sync_request(i):
            work_queue.get()
            if i % 3 == 0:
                status_resp = interface.communicate_stop_status()
                assert status_resp is not None
                assert status_resp.run_should_stop
            elif i % 3 == 2:
                summary_resp = interface.communicate_get_summary()
                assert summary_resp is not None
                assert hasattr(summary_resp, "item")
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

        status_resp = interface.communicate_network_status()
        assert status_resp is not None
        assert len(status_resp.network_responses) > 0
        assert status_resp.network_responses[0].http_status_code == 429


def test_resume_success(mocked_run, test_settings, mock_server, backend_interface):
    test_settings.update(resume="allow", source=wandb.sdk.wandb_settings.Source.INIT)
    mock_server.ctx["resume"] = True
    with backend_interface(initial_run=False) as interface:
        run_result = interface.communicate_run(mocked_run)
        assert run_result.HasField("error") is False
        assert run_result.run.starting_step == 16


def test_resume_error_never(mocked_run, test_settings, mock_server, backend_interface):
    test_settings.update(resume="never", source=wandb.sdk.wandb_settings.Source.INIT)
    mock_server.ctx["resume"] = True
    with backend_interface(initial_run=False) as interface:
        run_result = interface.communicate_run(mocked_run)
        assert run_result.HasField("error")
        assert (
            run_result.error.message
            == "resume='never' but run (%s) exists" % mocked_run.id
        )


def test_resume_error_must(mocked_run, test_settings, mock_server, backend_interface):
    test_settings.update(resume="must", source=wandb.sdk.wandb_settings.Source.INIT)
    mock_server.ctx["resume"] = False
    with backend_interface(initial_run=False) as interface:
        run_result = interface.communicate_run(mocked_run)
        assert run_result.HasField("error")
        assert (
            run_result.error.message
            == "resume='must' but run (%s) doesn't exist" % mocked_run.id
        )


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


@pytest.mark.parametrize("empty_query", [True, False])
@pytest.mark.parametrize("local_none", [True, False])
@pytest.mark.parametrize("outdated", [True, False])
def test_exit_poll_local(
    publish_util, mock_server, collect_responses, empty_query, local_none, outdated
):
    mock_server.ctx["out_of_date"] = outdated
    mock_server.ctx["empty_query"] = empty_query
    mock_server.ctx["local_none"] = local_none
    publish_util()

    out_of_date = collect_responses.poll_exit_resp.local_info.out_of_date
    if empty_query:
        assert out_of_date
    elif local_none:
        assert not out_of_date
    else:
        assert out_of_date == outdated


@pytest.mark.parametrize("messageLevel", ["a20", "None", ""])
def test_server_response_message_malformed_level(
    publish_util, mock_server, collect_responses, messageLevel
):
    mock_server.ctx["server_settings"] = True
    mock_server.ctx["server_messages"] = [
        {
            "messageLevel": messageLevel,
        },
    ]
    publish_util()
    server_messages = collect_responses.poll_exit_resp.server_messages.item
    assert len(server_messages) == 1
    assert server_messages[0].level == INFO


@pytest.mark.parametrize("messageLevel", ["30", 40])
def test_server_response_message_level(
    publish_util, mock_server, collect_responses, messageLevel
):
    mock_server.ctx["server_settings"] = True
    mock_server.ctx["server_messages"] = [
        {
            "messageLevel": messageLevel,
        },
    ]
    publish_util()
    server_messages = collect_responses.poll_exit_resp.server_messages.item
    assert len(server_messages) == 1
    assert server_messages[0].level == int(messageLevel)
