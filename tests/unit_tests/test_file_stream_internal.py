"""
file_stream tests.
"""

import json


def generate_history():
    history = []
    history.append(dict(step=0, data=dict(v1=1, v2=2, v3="dog", mystep=1)))
    history.append(dict(step=1, data=dict(v1=3, v2=8, v3="cat", mystep=2)))
    return history


def convert_history(history_data):
    history = []
    for h in history_data:
        step = h["step"]
        data = h["data"]
        data["_step"] = step
        history.append(data)
    return history


def assert_history(relay_server, run, publish_util, dropped=None, inject=None):

    with relay_server(inject=inject) as relay:
        history = generate_history()
        publish_util(run=run, history=history)

    print(relay.context.raw_data)

    context_history = relay.context.get_run_history(run.id, include_private=True)
    context_history.drop(columns=["__run_id"], inplace=True)

    converted_history = convert_history(history)
    assert context_history.to_dict(orient="records") == converted_history

    if dropped is not None:
        assert sum(relay.context.entries.get(run.id)["dropped"]) == dropped


# @pytest.mark.timeout(10)
def test_fstream_resp_limits_none(relay_server, user, mock_run, publish_util):
    # Test that no limits are applied when resp_limits is None.
    # This is the default behavior, no need to inject anything.
    assert_history(relay_server, mock_run(), publish_util)


def test_fstream_resp_limits_valid(
    relay_server,
    mock_run,
    publish_util,
    inject_file_stream_response,
):
    dynamic_settings = {"heartbeat_seconds": 10}
    resp_limits = json.dumps({"exitcode": None, "limits": dynamic_settings})

    run = mock_run(use_magic_mock=True)

    injected_response = inject_file_stream_response(run=run, body=resp_limits)
    print(injected_response)
    assert_history(relay_server, run, publish_util, inject=[injected_response])
    # note: we are not testing that the limits changed, only that they were accepted


def test_fstream_resp_limits_malformed(
    relay_server,
    mock_run,
    publish_util,
    inject_file_stream_response,
):
    resp_limits = json.dumps({"exitcode": None, "limits": "junk"})

    run = mock_run(use_magic_mock=True)

    injected_response = inject_file_stream_response(run=run, body=resp_limits)
    assert_history(relay_server, run, publish_util, inject=[injected_response])


def test_fstream_resp_malformed(
    relay_server,
    mock_run,
    publish_util,
    inject_file_stream_response,
):
    resp_invalid = '"invalid json {junk broken]"'

    run = mock_run(use_magic_mock=True)

    injected_response = inject_file_stream_response(run=run, body=resp_invalid)
    assert_history(relay_server, run, publish_util, inject=[injected_response])


def test_fstream_status_500(
    relay_server,
    mock_run,
    publish_util,
    inject_file_stream_response,
):
    run = mock_run(use_magic_mock=True)

    injected_response = inject_file_stream_response(run=run, status=500, counter=2)
    assert_history(relay_server, run, publish_util, inject=[injected_response])


def test_fstream_status_429(
    relay_server,
    mock_run,
    publish_util,
    inject_file_stream_response,
):
    """Rate limiting test."""

    run = mock_run(use_magic_mock=True)

    injected_response = inject_file_stream_response(run=run, status=429, counter=2)
    assert_history(relay_server, run, publish_util, inject=[injected_response])
