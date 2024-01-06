import os
import tempfile

import pytest
from wandb.sdk.lib import filesystem

# ----------------------------------
# wandb.save
# ----------------------------------


@pytest.mark.xfail(reason="This test is flaky")
def test_save_policy_symlink(mock_run, parse_records, record_q):
    run = mock_run()

    with open("test.rad", "w") as f:
        f.write("something")
    run.save("test.rad")
    assert os.path.exists(os.path.join(run.dir, "test.rad"))
    parsed = parse_records(record_q)
    file_record = parsed.files[0].files[0]
    assert file_record.path == "test.rad"
    assert file_record.policy == 2


@pytest.mark.xfail(reason="This test is flaky")
def test_save_policy_glob_symlink(mock_run, parse_records, record_q, capsys):
    run = mock_run()

    with open("test.rad", "w") as f:
        f.write("something")
    with open("foo.rad", "w") as f:
        f.write("something")
    run.save("*.rad")
    _, err = capsys.readouterr()
    assert "Symlinked 2 files" in err
    assert os.path.exists(os.path.join(run.dir, "test.rad"))
    assert os.path.exists(os.path.join(run.dir, "foo.rad"))

    # test_save_policy_glob_symlink
    parsed = parse_records(record_q)
    file_record = parsed.files[0].files[0]
    assert file_record.path == "*.rad"
    assert file_record.policy == 2


@pytest.mark.xfail(reason="This test is flaky")
def test_save_absolute_path(mock_run, parse_records, record_q, capsys):
    run = mock_run()
    root = tempfile.gettempdir()
    test_path = os.path.join(root, "test.txt")
    with open(test_path, "w") as f:
        f.write("something")

    run.save(test_path)
    _, err = capsys.readouterr()
    assert "Saving files without folders" in err
    assert os.path.exists(os.path.join(run.dir, "test.txt"))
    parsed = parse_records(record_q)
    file_record = parsed.files[0].files[0]
    assert file_record.path == "test.txt"
    assert file_record.policy == 2


@pytest.mark.xfail(reason="This test is flaky")
def test_save_relative_path(mock_run, parse_records, record_q):
    run = mock_run()
    root = tempfile.gettempdir()
    test_path = os.path.join(root, "tmp", "test.txt")
    print("DAMN", os.path.dirname(test_path))
    filesystem.mkdir_exists_ok(os.path.dirname(test_path))
    with open(test_path, "w") as f:
        f.write("something")
    run.save(test_path, base_path=root, policy="now")
    assert os.path.exists(os.path.join(run.dir, test_path))
    parsed = parse_records(record_q)
    file_record = parsed.files[0].files[0]
    assert file_record.path == os.path.relpath(test_path, root)
    assert file_record.policy == 0
