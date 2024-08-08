"""
file_stream tests.
"""


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


def assert_history(publish_util, dropped=None):
    history = generate_history()
    ctx_util = publish_util(history=history)

    converted_history = convert_history(history)
    assert ctx_util.history == converted_history
    if dropped is not None:
        assert ctx_util.dropped_chunks == dropped


def test_fstream_requests_error(
    publish_util, mock_server, inject_requests, mocker, capsys
):
    # inject a requests error, not a http error

    match = inject_requests.Match(path_suffix="/file_stream")
    inject_requests.add(match=match, requests_error=True)
    history = generate_history()
    publish_util(history=history)
    stdout, stderr = capsys.readouterr()
    assert "Dropped streaming file chunk" in stderr
