import re

import pytest
from wandb.sdk.launch.builder.templates._wandb_bootstrap import TORCH_DEP_REGEX


@pytest.mark.parametrize(
    "dep,expected",
    [
        ("torch", None),
        ("torch==1.7.0", (None, None)),
        ("torch==1.7.0+cu110", (None, "+cu110")),
        (
            "torch==1.7.0+cu110 -f https://download.pytorch.org/whl/torch_stable.html",
            (None, "+cu110"),
        ),
        (
            "torchvision==1.7.0+cu110 -f https://download.pytorch.org/whl/torch_stable.html",
            ("vision", "+cu110"),
        ),
        ("torch==2.0.1+cpu", (None, "+cpu")),
        ("torchvision==2.0.1+cpu", ("vision", "+cpu")),
        ("torchaudio==2.0.1+cpu", ("audio", "+cpu")),
    ],
)
def test_torch_dep_regex(dep, expected):
    match = re.match(TORCH_DEP_REGEX, dep)
    if expected is None:
        assert match is None
        return
    assert match is not None
    assert match.groups() == expected
