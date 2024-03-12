import pathlib

# ----------------------------------
# wandb.save
# ----------------------------------


def test_save_relative_file(
    monkeypatch,
    tmp_path,
    mock_run,
    parse_records,
    record_q,
):
    # Use a fake working directory for the test.
    monkeypatch.chdir(tmp_path)
    pathlib.Path("test.rad").touch()

    run = mock_run()
    run.save("test.rad", policy="now")

    assert (pathlib.Path(run.dir) / "test.rad").exists()
    parsed = parse_records(record_q)
    file_record = parsed.files[0].files[0]
    assert file_record.path == "test.rad"


def test_save_relative_glob(
    monkeypatch,
    tmp_path,
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
    assert (pathlib.Path(run.dir) / "test.rad").exists()
    assert (pathlib.Path(run.dir) / "foo.rad").exists()
    parsed = parse_records(record_q)
    file_record = parsed.files[0].files[0]
    assert file_record.path == "*.rad"


def test_save_absolute_glob(
    tmp_path: pathlib.Path,
    mock_run,
    parse_records,
    record_q,
):
    test_path = tmp_path / "subdir" / "test.txt"
    test_path.parent.mkdir()
    test_path.touch()

    run = mock_run()
    run.save(str((tmp_path / "*" / "test.txt").absolute()), policy="now")

    parsed = parse_records(record_q)
    file_record = parsed.files[0].files[0]
    assert file_record.path == "test.txt"


def test_save_absolute_path(
    tmp_path: pathlib.Path,
    mock_run,
    parse_records,
    record_q,
):
    test_path = (tmp_path / "test.txt").absolute()
    test_path.touch()

    run = mock_run()
    run.save(str(test_path), policy="now")

    assert (pathlib.Path(run.dir) / "test.txt").exists()
    parsed = parse_records(record_q)
    file_record = parsed.files[0].files[0]
    assert file_record.path == "test.txt"


def test_save_relative_path(
    tmp_path: pathlib.Path,
    mock_run,
    parse_records,
    record_q,
):
    test_path = tmp_path / "subdir" / "test.txt"
    test_path.parent.mkdir(exist_ok=True)
    test_path.touch()

    run = mock_run()
    run.save(str(test_path), base_path=str(tmp_path), policy="now")

    assert (pathlib.Path(run.dir) / "subdir" / "test.txt").exists()
    parsed = parse_records(record_q)
    file_record = parsed.files[0].files[0]
    assert file_record.path == "subdir/test.txt"
