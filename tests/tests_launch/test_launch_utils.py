import pytest
import random
from wandb.errors import LaunchError

from ..utils import diff_pip_requirements

REQUIREMENT_FILE_BASIC = [
    "package-one==1.0.0",
    "# This is a comment in requirements.txt",
    "package-two",
]

REQUIREMENT_FILE_BASIC_2 = [
    "package-one==2.0.0",
    "package-two==1.0.0",
]

REQUIREMENT_FILE_GIT = [
    "package-one==1.9.4",
    "git+https://github.com/path/to/package-two@41b95ec#egg=package-two",
]


def test_diff_pip_requirements():

    # Order in requirements file should not matter
    diff = diff_pip_requirements(
        REQUIREMENT_FILE_BASIC, random.shuffle(REQUIREMENT_FILE_BASIC)
    )
    assert not diff

    # Empty requirements file should parse fine, but appear in diff
    diff = diff_pip_requirements([], REQUIREMENT_FILE_BASIC)
    assert len(diff) == 2

    # Invalid requirements should throw LaunchError
    with pytest.raises(LaunchError):
        diff_pip_requirements(REQUIREMENT_FILE_BASIC, ["42=="])

    # Version mismatch should appear in diff
    diff = diff_pip_requirements(REQUIREMENT_FILE_BASIC, REQUIREMENT_FILE_BASIC_2)
    assert len(diff) == 2

    # Github package should parse fine, but appear in diff
    diff = diff_pip_requirements(REQUIREMENT_FILE_BASIC, REQUIREMENT_FILE_GIT)
    assert len(diff) == 2
