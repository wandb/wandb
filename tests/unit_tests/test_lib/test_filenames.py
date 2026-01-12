from __future__ import annotations

from pathlib import Path

import pytest
from wandb.sdk.lib.filenames import exclude_wandb_fn, filtered_dir


def test_filtered_dir_one_parameter(tmp_path: Path):
    with open(tmp_path / "foo.txt", "w") as f:
        f.write("test")
    filtered_dir(tmp_path, lambda path: True, lambda path: False)


def test_filtered_dir_two_parameters(tmp_path: Path):
    with open(tmp_path / "foo.txt", "w") as f:
        f.write("test")
    filtered_dir(tmp_path, lambda path, root: True, lambda path, root: False)


@pytest.mark.parametrize(
    "root,path,expected",
    [
        ["/app", "/app/wandb/foo", True],
        ["/app", "/app/.wandb/foo", True],
        ["/app", "/app/foo", False],
        ["/app", "/app/foo/wandb", False],
        ["/app", "/app/foo/.wandb", False],
        ["/app", "/app/foo/wandb/foo", False],
        ["/app", "/app/foo/.wandb/foo", False],
        ["/wandb", "/wandb/wandb/foo", True],
        ["/wandb", "/wandb/.wandb/foo", True],
        ["/wandb", "/wandb/foo", False],
        ["/wandb", "/wandb/foo/wandb", False],
        ["/wandb", "/wandb/foo/.wandb", False],
        ["/wandb", "/wandb/foo/wandb/foo", False],
        ["/wandb", "/wandb/foo/.wandb/foo", False],
    ],
)
def test_exclude_wandb_fn(root, path, expected):
    assert exclude_wandb_fn(path, root) == expected
