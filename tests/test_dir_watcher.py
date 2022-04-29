"""dir_watcher tests"""

from typing import Callable, TYPE_CHECKING
from unittest.mock import Mock, call

import pytest
import py.path

from wandb import Settings
from wandb.filesync.dir_watcher import DirWatcher, PolicyEnd, PolicyLive, PolicyNow
from wandb.sdk.internal.file_pusher import FilePusher

if TYPE_CHECKING:
    from wandb.sdk.interface.interface import PolicyName


@pytest.fixture
def file_pusher():
    return Mock()


@pytest.fixture
def settings():
    return Mock(ignore_globs=[])


@pytest.fixture
def dir_watcher(settings, file_pusher, tmpdir: py.path.local) -> DirWatcher:
    return DirWatcher(
        settings=settings,
        api=Mock(),
        file_pusher=file_pusher,
        file_dir=str(tmpdir),
        file_observer_for_testing=Mock(),
    )


@pytest.mark.parametrize(
    ["write_file", "expect_called"],
    [
        (lambda f: f.write_binary(b"content"), True),
        (lambda f: f.write_binary(b""), False),
        (lambda f: None, False),
    ],
)
def test_dirwatcher_update_policy_live_calls_file_changed_iff_file_nonempty(
    tmpdir: py.path.local,
    file_pusher: FilePusher,
    dir_watcher: DirWatcher,
    write_file: Callable[[py.path.local], None],
    expect_called: bool,
):
    """
    Test that if a file exists, the update policy is called
    """
    f = tmpdir / "my-file.txt"
    write_file(f)
    dir_watcher.update_policy(str(f), "live")
    assert file_pusher.file_changed.called == expect_called


@pytest.mark.parametrize(
    ["policy", "expect_called"],
    [
        ("now", True),
        ("live", True),
        ("end", False),
    ],
)
def test_dirwatcher_update_policy_on_nonexistent_file_calls_file_changed_when_file_created_iff_policy_now_or_live(
    tmpdir: py.path.local,
    file_pusher: FilePusher,
    dir_watcher: DirWatcher,
    policy: "PolicyName",
    expect_called: bool,
):
    f = tmpdir / "my-file.txt"
    dir_watcher.update_policy(str(f), policy)

    f.write_binary(b"content")

    file_pusher.file_changed.assert_not_called()
    dir_watcher._on_file_created(Mock(src_path=str(f)))
    assert file_pusher.file_changed.called == expect_called


def test_dirwatcher_finish_uploads_unheardof_files(
    tmpdir: py.path.local, file_pusher: FilePusher, dir_watcher: DirWatcher
):
    f = tmpdir / "my-file.txt"
    f.write_binary(b"content")
    dir_watcher.finish()
    file_pusher.file_changed.assert_called_once_with("my-file.txt", str(f), copy=False)


def test_dirwatcher_finish_skips_now_files(
    tmpdir: py.path.local, file_pusher: FilePusher, dir_watcher: DirWatcher
):
    f = tmpdir / "my-file.txt"
    dir_watcher.update_policy(str(f), "now")
    f.write_binary(b"content")
    dir_watcher.finish()
    file_pusher.file_changed.assert_not_called()


def test_dirwatcher_finish_uploads_end_files(
    tmpdir: py.path.local, file_pusher: FilePusher, dir_watcher: DirWatcher
):
    f = tmpdir / "my-file.txt"
    f.write_binary(b"content")
    dir_watcher.update_policy(str(f), "end")
    dir_watcher.finish()
    file_pusher.file_changed.assert_called_once_with("my-file.txt", str(f), copy=False)


@pytest.mark.parametrize("changed", [True, False])
def test_dirwatcher_finish_uploads_live_files_iff_changed(
    tmpdir: py.path.local,
    file_pusher: FilePusher,
    dir_watcher: DirWatcher,
    changed: bool,
):
    f = tmpdir / "my-file.txt"
    f.write_binary(b"content")
    dir_watcher.update_policy(str(f), "live")
    if changed:
        f.write_binary(b"new content")

    file_pusher.file_changed.reset_mock()
    dir_watcher.finish()
    assert file_pusher.file_changed.called == changed


@pytest.mark.parametrize("ignore", [True, False])
def test_dirwatcher_finish_skips_ignoreglob_files(
    tmpdir: py.path.local,
    file_pusher: FilePusher,
    dir_watcher: DirWatcher,
    settings,
    ignore: bool,
):
    if ignore:
        settings.ignore_globs = ["*.txt"]

    f = tmpdir / "my-file.txt"
    f.write_binary(b"content")
    dir_watcher.update_policy(str(f), "end")
    dir_watcher.finish()
    assert file_pusher.file_changed.called == (not ignore)


def test_dirwatcher_prefers_live_policy_when_multiple_rules_match_file(
    tmpdir: py.path.local, dir_watcher: DirWatcher
):
    f = tmpdir / "my-file.txt"
    f.write_binary(b"content")
    dir_watcher.update_policy("*.txt", "live")
    dir_watcher.update_policy("my-file.*", "end")
    dir_watcher.update_policy("my-*.txt", "now")
    assert isinstance(
        dir_watcher._get_file_event_handler(str(f), "my-file.txt"), PolicyLive
    )


@pytest.mark.skip(
    reason="Surprisingly, this test fails. Do we want to change behavior to make it pass? TODO(spencerpearson)"
)
def test_dirwatcher_can_overwrite_policy_for_file(
    tmpdir: py.path.local, dir_watcher: DirWatcher
):
    f = tmpdir / "my-file.txt"
    f.write_binary(b"content")
    dir_watcher.update_policy("my-file.txt", "live")
    assert isinstance(
        dir_watcher._get_file_event_handler(str(f), "my-file.txt"), PolicyLive
    )
    dir_watcher.update_policy("my-file.txt", "end")
    assert isinstance(
        dir_watcher._get_file_event_handler(str(f), "my-file.txt"), PolicyEnd
    )


def test_policylive_uploads_nonempty_unchanged_file_on_modified(
    tmpdir: py.path.local, file_pusher: Mock
):
    f = tmpdir / "my-file.txt"
    f.write_binary(b"content")
    policy = PolicyLive(str(f), f.basename, Mock(), file_pusher)
    policy.on_modified()
    file_pusher.file_changed.assert_called_once_with(f.basename, str(f))


def test_policylive_ratelimits_modified_file_reupload(
    tmpdir: py.path.local, file_pusher: Mock
):
    elapsed = 0
    f = tmpdir / "my-file.txt"
    f.write_binary(b"content")
    policy = PolicyLive(
        str(f), f.basename, Mock(), file_pusher, clock_for_testing=lambda: elapsed
    )
    policy.on_modified()

    threshold = max(
        PolicyLive.RATE_LIMIT_SECONDS,
        PolicyLive.min_wait_for_size(len(f.read_binary())),
    )

    file_pusher.reset_mock()
    f.write_binary(b"new content")
    elapsed = threshold - 1
    policy.on_modified()
    file_pusher.file_changed.assert_not_called()

    elapsed = threshold + 1
    policy.on_modified()
    file_pusher.file_changed.assert_called()


def test_policylive_forceuploads_on_finish(tmpdir: py.path.local, file_pusher: Mock):
    f = tmpdir / "my-file.txt"
    f.write_binary(b"content")
    policy = PolicyLive(
        str(f), f.basename, Mock(), file_pusher, clock_for_testing=lambda: 0
    )
    policy.on_modified()
    file_pusher.reset_mock()

    f.write_binary(b"new content")
    policy.on_modified()  # modifying the file shouldn't re-upload it because of the rate-limiting...
    file_pusher.file_changed.assert_not_called()
    policy.finish()  # ...but finish() should force a re-upload
    file_pusher.file_changed.assert_called()


def test_policynow_uploads_on_modified_iff_not_already_uploaded(
    tmpdir: py.path.local, file_pusher: Mock
):
    f = tmpdir / "my-file.txt"
    f.write_binary(b"content")
    policy = PolicyNow(str(f), f.basename, Mock(), file_pusher)

    policy.on_modified()
    file_pusher.file_changed.assert_called()
    file_pusher.reset_mock()
    policy.on_modified()
    file_pusher.file_changed.assert_not_called()
