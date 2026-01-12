from __future__ import annotations

import pytest
from wandb.filesync import stats


@pytest.mark.parametrize(
    ["init_file_kwargs", "expected_stats"],
    [
        (
            {"save_name": "foo", "size": 10},
            stats.FileCountsByCategory(artifact=0, wandb=0, media=0, other=1),
        ),
        (
            {"save_name": "foo", "size": 10, "is_artifact_file": True},
            stats.FileCountsByCategory(artifact=1, wandb=0, media=0, other=0),
        ),
        (
            {"save_name": "wandb/foo", "size": 10},
            stats.FileCountsByCategory(artifact=0, wandb=1, media=0, other=0),
        ),
        (
            {"save_name": "media/foo", "size": 10},
            stats.FileCountsByCategory(artifact=0, wandb=0, media=1, other=0),
        ),
        # wandb-ness and media-ness are ignored because this path is absolute
        # so we have no good way to tell if the wandb/ or media/ directory
        # is important or happenstance
        (
            {
                "save_name": "/absolute/path/to/some/wandb/media/foo",
                "size": 10,
                "is_artifact_file": True,
            },
            stats.FileCountsByCategory(artifact=1, wandb=0, media=0, other=0),
        ),
        (
            {"save_name": "/absolute/path/to/some/wandb/media/foo", "size": 10},
            stats.FileCountsByCategory(artifact=0, wandb=0, media=0, other=1),
        ),
    ],
)
def test_file_counts_by_category(
    init_file_kwargs: dict,
    expected_stats: stats.FileCountsByCategory,
):
    s = stats.Stats()
    s.init_file(**init_file_kwargs)
    assert s.file_counts_by_category() == expected_stats


def test_file_counts_by_category_adds_counts():
    s = stats.Stats()
    s.init_file("foo", 10)
    s.init_file("bar", 10)
    s.init_file("wandb/bar", 10)
    assert s.file_counts_by_category() == stats.FileCountsByCategory(
        artifact=0, wandb=1, media=0, other=2
    )


class TestSummary:
    def test_init_file(self):
        s = stats.Stats()
        s.init_file("foo", 10)
        assert s.summary() == stats.Summary(
            uploaded_bytes=0, total_bytes=10, deduped_bytes=0
        )

    def test_update_uploaded_file_updates_uploaded_bytes(self):
        s = stats.Stats()
        s.init_file("foo", 10)
        s.update_uploaded_file("foo", 7)
        assert s.summary() == stats.Summary(
            uploaded_bytes=7, total_bytes=10, deduped_bytes=0
        )

    def test_set_file_deduped_updates_deduped_bytes(self):
        s = stats.Stats()
        s.init_file("foo", 10)
        s.set_file_deduped("foo")
        assert s.summary() == stats.Summary(
            uploaded_bytes=10, total_bytes=10, deduped_bytes=10
        )


def test_failed_file_resets_summary_uploaded_bytes():
    s = stats.Stats()
    s.init_file("foo", 10)
    s.init_file("bar", 10)
    s.update_uploaded_file("foo", 7)
    s.update_uploaded_file("bar", 8)

    assert s.summary().uploaded_bytes == 15

    s.update_failed_file("foo")

    assert s.summary().uploaded_bytes == 8
