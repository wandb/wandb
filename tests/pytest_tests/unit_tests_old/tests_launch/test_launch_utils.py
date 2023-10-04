import random
from typing import List

import pytest
from wandb.sdk.launch.errors import LaunchError
from wandb.sdk.launch.utils import (
    LAUNCH_DEFAULT_PROJECT,
    diff_pip_requirements,
    make_queue_uri,
    parse_wandb_uri,
)

REQUIREMENT_FILE_BASIC: List[str] = [
    "package-one==1.0.0",
    "# This is a comment in requirements.txt",
    "package-two",
    "package-three>1.0.0",
]

REQUIREMENT_FILE_BASIC_2: List[str] = [
    "package-one==2.0.0",
    "package-two>=1.0.0",
    "package-three==0.0.9",
]

REQUIREMENT_FILE_GIT: List[str] = [
    "package-one==1.9.4",
    "git+https://github.com/path/to/package-two@41b95ec#egg=package-two",
]


def test_diff_pip_requirements():
    # Order in requirements file should not matter
    _shuffled = REQUIREMENT_FILE_BASIC.copy()
    random.shuffle(_shuffled)
    diff = diff_pip_requirements(REQUIREMENT_FILE_BASIC, _shuffled)
    assert not diff

    # Empty requirements file should parse fine, but appear in diff
    diff = diff_pip_requirements([], REQUIREMENT_FILE_BASIC)
    assert len(diff) == 3

    # Invalid requirements should throw LaunchError
    with pytest.raises(LaunchError):
        diff_pip_requirements(REQUIREMENT_FILE_BASIC, ["4$$%2=="])
    with pytest.raises(LaunchError):
        diff_pip_requirements(REQUIREMENT_FILE_BASIC, ["foo~~~~bar"])

    # Version mismatch should appear in diff
    diff = diff_pip_requirements(REQUIREMENT_FILE_BASIC, REQUIREMENT_FILE_BASIC_2)
    assert len(diff) == 3

    # Github package should parse fine, but appear in diff
    diff = diff_pip_requirements(REQUIREMENT_FILE_BASIC, REQUIREMENT_FILE_GIT)
    assert len(diff) == 3


def test_parse_wandb_uri_invalid_uri():
    with pytest.raises(LaunchError):
        parse_wandb_uri("invalid_uri")


def test_make_queue_uri():
    with pytest.raises(ValueError):
        make_queue_uri(None, None, "queue")

    with pytest.raises(ValueError):
        make_queue_uri("entity", None, "queue")

    with pytest.raises(ValueError):
        make_queue_uri(None, "project", "queue")

    assert (
        make_queue_uri("entity", "project", "queue") == "queue:0:entity:project:queue"
    )
    assert (
        make_queue_uri("entity", LAUNCH_DEFAULT_PROJECT, "queue")
        == "queue:1:entity:queue"
    )
