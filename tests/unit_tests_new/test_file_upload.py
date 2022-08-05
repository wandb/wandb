"""
file upload tests.
"""

import os


def test_file_upload_good(mock_run, publish_util, relay_server, user):
    run = mock_run(use_magic_mock=True)

    def begin_fn(interface):
        with open(os.path.join(run.dir, "test.txt"), "w") as f:
            f.write("TEST TEST")

    files = [dict(files_dict=dict(files=[("test.txt", "now")]))]
    with relay_server() as relay:
        publish_util(run, begin_cb=begin_fn, files=files)

    assert "test.txt" in relay.context.get_run_uploaded_files(run.id)
