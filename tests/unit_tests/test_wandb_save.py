import os
import pathlib
import platform

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
    if platform.system() == "Windows":
        assert "Linked 2 files" in err
    else:
        assert "Symlinked 2 files" in err
    assert pathlib.Path(run.dir, "test.rad").exists()
    assert pathlib.Path(run.dir, "foo.rad").exists()
    parsed = parse_records(record_q)
    paths = set([f.path for f in parsed.files[0].files])
    assert paths == set(["test.rad", "foo.rad"])


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
    paths = set([pathlib.Path(f.path) for f in parsed.files[0].files])
    assert paths == set([pathlib.Path("subdir", "test.txt")])


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
    paths = set([pathlib.Path(f.path) for f in parsed.files[0].files])
    assert paths == set(
        [
            pathlib.Path("dir", "x", "file.txt"),
            pathlib.Path("dir", "y", "file.txt"),
        ]
    )


def test_save_file_in_run_dir(mock_run):
    run = mock_run()
    file = pathlib.Path(run.dir, "my_file.txt")
    file.parent.mkdir(parents=True)
    file.touch()

    run.save(file, base_path=run.dir)

    assert file.exists()
    assert not file.is_symlink()


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


def test_save_bytes_glob(monkeypatch, tmp_path: pathlib.Path, mock_run):
    # Use a fake working directory for the test.
    monkeypatch.chdir(tmp_path)
    pathlib.Path("my_file.txt").touch()

    run = mock_run()
    run.save(b"my_file.txt")

    assert pathlib.Path(run.dir, "my_file.txt").exists()


def test_save_g3_path_warns(mock_run, capsys):
    mock_run().save("gs://file.txt")

    assert "cloud storage url, can't save" in capsys.readouterr().err


def test_save_s3_path_warns(mock_run, capsys):
    mock_run().save("s3://file.txt")

    assert "cloud storage url, can't save" in capsys.readouterr().err


def test_save_hardlink_fallback_when_symlink_fails(
    monkeypatch,
    mock_run,
    parse_records,
    record_q,
    capsys,
):
    run = mock_run()

    base_dir = pathlib.Path(run.dir).parent / "hl_src"
    base_dir.mkdir(parents=True, exist_ok=True)
    (base_dir / "a.hl").write_text("a")
    (base_dir / "b.hl").write_text("b")

    # Force symlink creation to fail so the code falls back to hardlinks.
    def _raise_symlink(*_args, **_kwargs):
        raise OSError("symlink not permitted")

    monkeypatch.setattr(pathlib.Path, "symlink_to", _raise_symlink)

    run.save(str(base_dir / "*.hl"), base_path=str(base_dir), policy="now")

    _, err = capsys.readouterr()
    assert "Linked 2 files into the W&B run directory (hardlinks)" in err
    assert (pathlib.Path(run.dir) / "a.hl").exists()
    assert (pathlib.Path(run.dir) / "b.hl").exists()

    parsed = parse_records(record_q)
    paths = {f.path for f in parsed.files[0].files}
    assert paths == {"a.hl", "b.hl"}


def test_save_copy_fallback_when_links_unavailable(
    monkeypatch,
    mock_run,
    parse_records,
    record_q,
    capsys,
):
    run = mock_run()

    base_dir = pathlib.Path(run.dir).parent / "cp_src"
    base_dir.mkdir(parents=True, exist_ok=True)
    (base_dir / "a.cpy").write_text("a")
    (base_dir / "b.cpy").write_text("b")

    # Force both symlink *and* hardlink creation to fail to trigger copy.
    def _raise_symlink(*_args, **_kwargs):
        raise OSError("symlink not permitted")

    monkeypatch.setattr(pathlib.Path, "symlink_to", _raise_symlink)

    def _raise_link(*_args, **_kwargs):
        raise OSError("hardlink not permitted")

    monkeypatch.setattr(os, "link", _raise_link)

    # Exercise internal downgrade logic when copying.
    run.save(str(base_dir / "*.cpy"), base_path=str(base_dir), policy="live")

    _, err = capsys.readouterr()
    assert "Copied 2 files" in err
    assert (pathlib.Path(run.dir) / "a.cpy").exists()
    assert (pathlib.Path(run.dir) / "b.cpy").exists()

    parsed = parse_records(record_q)
    paths = {f.path for f in parsed.files[0].files}
    assert paths == {"a.cpy", "b.cpy"}
