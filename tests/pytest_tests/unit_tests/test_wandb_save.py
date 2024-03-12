import pathlib

import pytest

# ----------------------------------
# wandb.save
# ----------------------------------


def test_save_relative_path(
    monkeypatch,
    tmp_path: pathlib.Path,
    mock_run,
    parse_records,
    record_q,
):
    # Use a fake working directory for the test.
    monkeypatch.chdir(tmp_path)
    pathlib.Path("test.rad").touch()

    run = mock_run()
    run.save("test.rad", policy="now")

    assert pathlib.Path(run.dir, "test.rad").exists()
    parsed = parse_records(record_q)
    file_record = parsed.files[0].files[0]
    assert file_record.path == "test.rad"


def test_save_relative_base_path(
    monkeypatch,
    tmp_path: pathlib.Path,
    mock_run,
    parse_records,
    record_q,
):
    # Use a fake working directory for the test.
    monkeypatch.chdir(tmp_path)
    test_file = pathlib.Path("dir", "subdir", "file.txt")
    test_file.parent.mkdir(parents=True)
    test_file.touch()

    run = mock_run()
    run.save(str(test_file), base_path="dir")

    assert pathlib.Path(run.dir, "subdir", "file.txt").exists()
    parsed = parse_records(record_q)
    file_record = parsed.files[0].files[0]
    assert pathlib.Path(file_record.path) == pathlib.Path("subdir", "file.txt")


def test_save_relative_path_glob_files(
    monkeypatch,
    tmp_path: pathlib.Path,
    mock_run,
    parse_records,
    record_q,
    capsys,
):
    # Use a fake working directory for the test.
    monkeypatch.chdir(tmp_path)
    pathlib.Path("test.rad").touch()
    pathlib.Path("foo.rad").touch()

    run = mock_run()
    run.save("*.rad", policy="now")

    _, err = capsys.readouterr()
    assert "Symlinked 2 files" in err
    assert pathlib.Path(run.dir, "test.rad").exists()
    assert pathlib.Path(run.dir, "foo.rad").exists()
    parsed = parse_records(record_q)
    file_record = parsed.files[0].files[0]
    assert file_record.path == "*.rad"


def test_save_valid_absolute_glob(
    tmp_path: pathlib.Path,
    mock_run,
    parse_records,
    record_q,
):
    (tmp_path / "dir" / "globbed" / "subdir").mkdir(parents=True)
    (tmp_path / "dir" / "globbed" / "subdir" / "test.txt").touch()
    test_glob = tmp_path / "dir" / "*" / "subdir" / "*.txt"
    assert test_glob.is_absolute()

    run = mock_run()
    run.save(str(test_glob), policy="now")

    parsed = parse_records(record_q)
    file_record = parsed.files[0].files[0]
    assert pathlib.Path(file_record.path) == pathlib.Path("subdir", "*.txt")


def test_save_valid_absolute_glob_base_path(
    tmp_path: pathlib.Path,
    mock_run,
    parse_records,
    record_q,
):
    (tmp_path / "dir" / "x").mkdir(parents=True)
    (tmp_path / "dir" / "y").mkdir(parents=True)
    (tmp_path / "dir" / "x" / "file.txt").touch()
    (tmp_path / "dir" / "y" / "file.txt").touch()

    run = mock_run()
    run.save(
        str(tmp_path / "dir" / "*" / "file.txt"),
        base_path=tmp_path,
    )

    assert pathlib.Path(run.dir, "dir", "x", "file.txt").exists()
    assert pathlib.Path(run.dir, "dir", "y", "file.txt").exists()
    parsed = parse_records(record_q)
    file_record = parsed.files[0].files[0]
    assert pathlib.Path(file_record.path) == pathlib.Path("dir", "*", "file.txt")


def test_save_base_path_glob_first_directory_invalid(mock_run):
    with pytest.raises(ValueError, match="may not start with '*'"):
        mock_run().save("dir/*/file.txt", base_path="dir")


def test_save_glob_first_directory_invalid(mock_run):
    with pytest.raises(ValueError, match="may not start with '*'"):
        mock_run().save("*/file.txt")


def test_save_absolute_glob_first_directory_invalid(tmp_path: pathlib.Path, mock_run):
    with pytest.raises(ValueError, match="may not start with '*"):
        mock_run().save(str(tmp_path / "*" / "file.txt"), base_path=str(tmp_path))


def test_save_absolute_glob_last_directory_invalid(tmp_path: pathlib.Path, mock_run):
    # For absolute globs without a base path, files are saved in the directory
    # named by the second-to-last path component of the glob. In this case,
    # that component is "*", which we do not support.
    with pytest.raises(ValueError, match="may not start with '*'"):
        mock_run().save(str(tmp_path / "*" / "file.txt"))


def test_save_dotdot(tmp_path: pathlib.Path, mock_run, parse_records, record_q):
    test_path = tmp_path / "subdir" / "and_more" / ".." / "nvm.txt"
    assert ".." in str(test_path)
    test_path.resolve().parent.mkdir()
    test_path.resolve().touch()

    run = mock_run()
    run.save(str(test_path), policy="now")

    assert pathlib.Path(run.dir, "subdir", "nvm.txt").exists()
    parsed = parse_records(record_q)
    file_record = parsed.files[0].files[0]
    assert pathlib.Path(file_record.path) == pathlib.Path("subdir", "nvm.txt")


def test_save_cannot_escape_base_path(tmp_path: pathlib.Path, mock_run):
    with pytest.raises(ValueError, match="may not walk above the base path"):
        mock_run().save(
            str(tmp_path / ".." / "file.txt"),
            base_path=str(tmp_path),
        )
