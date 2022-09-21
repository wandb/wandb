"""
file upload tests.
"""


import os


def test_file_upload_inject(mocked_run, publish_util, mock_server, inject_requests):
    def begin_fn(interface):
        with open(os.path.join(mocked_run.dir, "test.txt"), "w") as f:
            f.write("TEST TEST")

    query_str = f"file=test.txt&run={mocked_run.id}"
    match = inject_requests.Match(path_suffix="/storage", query_str=query_str, count=2)
    inject_requests.add(match=match, http_status=500)

    files = [dict(files_dict=dict(files=[("test.txt", "now")]))]
    ctx_util = publish_util(files=files, begin_cb=begin_fn)
    assert "test.txt" in ctx_util.file_names


def test_file_upload_azure_good(mocked_run, publish_util, mock_server):
    mock_server.set_context("emulate_azure", True)

    def begin_fn(interface):
        with open(os.path.join(mocked_run.dir, "test.txt"), "w") as f:
            f.write("TEST TEST")

    files = [dict(files_dict=dict(files=[("test.txt", "now")]))]
    ctx_util = publish_util(files=files, begin_cb=begin_fn)
    assert "test.txt" in ctx_util.file_names


def test_file_upload_azure_inject(
    mocked_run, publish_util, mock_server, inject_requests
):
    mock_server.set_context("emulate_azure", True)

    def begin_fn(interface):
        with open(os.path.join(mocked_run.dir, "test.txt"), "w") as f:
            f.write("TEST TEST")

    suffix = f"/azure/{mocked_run.id}/test.txt"
    match = inject_requests.Match(path_suffix=suffix, count=3)
    inject_requests.add(match=match, http_status=500)

    files = [dict(files_dict=dict(files=[("test.txt", "now")]))]
    ctx_util = publish_util(files=files, begin_cb=begin_fn)
    # TODO: this is currently not causing an HTTPResponseError in internal_api
    assert "test.txt" in ctx_util.file_names
