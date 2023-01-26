from typing import Callable

import pytest
from wandb.filesync import stats


@pytest.mark.parametrize(
    ["init_file", "expected_stats"],
    [
        (
            lambda stats: stats.init_file("foo", 10),
            stats.FileCountsByCategory(artifact=0, wandb=0, media=0, other=1),
        ),
        (
            lambda stats: stats.init_file("foo", 10, is_artifact_file=True),
            stats.FileCountsByCategory(artifact=1, wandb=0, media=0, other=0),
        ),
        (
            lambda stats: stats.init_file("wandb/foo", 10),
            stats.FileCountsByCategory(artifact=0, wandb=1, media=0, other=0),
        ),
        (
            lambda stats: stats.init_file("media/foo", 10),
            stats.FileCountsByCategory(artifact=0, wandb=0, media=1, other=0),
        ),
        (
            lambda stats: stats.init_file(
                "/absolute/path/to/some/wandb/media/foo", 10, is_artifact_file=True
            ),
            stats.FileCountsByCategory(artifact=1, wandb=0, media=0, other=0),
        ),
        (
            lambda stats: stats.init_file("/absolute/path/to/some/wandb/media/foo", 10),
            stats.FileCountsByCategory(artifact=0, wandb=0, media=0, other=1),
        ),
        (
            lambda stats: (
                stats.init_file("foo", 10),
                stats.init_file("wandb/bar", 10),
            ),
            stats.FileCountsByCategory(artifact=0, wandb=1, media=0, other=1),
        ),
    ],
)
def test_file_counts_by_category(
    init_file: Callable[[stats.Stats], None],
    expected_stats: stats.FileCountsByCategory,
):
    s = stats.Stats()
    init_file(s)
    assert s.file_counts_by_category() == expected_stats


@pytest.mark.parametrize(
    ["init_file", "expected_summary"],
    [
        (
            lambda stats: stats.init_file("foo", 10),
            stats.Summary(uploaded_bytes=0, total_bytes=10, deduped_bytes=0),
        ),
        (
            lambda stats: (
                stats.init_file("foo", 10),
                stats.update_uploaded_file("foo", 7),
            ),
            stats.Summary(uploaded_bytes=7, total_bytes=10, deduped_bytes=0),
        ),
        (
            lambda stats: (
                stats.init_file("foo", 10),
                stats.set_file_deduped("foo"),
            ),
            stats.Summary(uploaded_bytes=10, total_bytes=10, deduped_bytes=10),
        ),
    ],
)
def test_summary(
    init_file: Callable[[stats.Stats], None],
    expected_summary: stats.Summary,
):
    s = stats.Stats()
    init_file(s)
    assert s.summary() == expected_summary


def test_failed_file_resets_summary_uploaded_bytes():
    s = stats.Stats()
    s.init_file("foo", 10)
    s.init_file("bar", 10)
    s.update_uploaded_file("foo", 7)
    s.update_uploaded_file("bar", 8)

    assert s.summary().uploaded_bytes == 15

    s.update_failed_file("foo")

    assert s.summary().uploaded_bytes == 8
