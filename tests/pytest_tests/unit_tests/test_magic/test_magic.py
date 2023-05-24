import pytest
from pathlib import Path
from wandb.apis.magic import auto_wandb
import subprocess


def run_black(file_path):
    try:
        subprocess.run(["black", file_path, "--quiet"], check=True)
    except subprocess.CalledProcessError as e:
        print("Black formatting failed.")
        print(e)


@pytest.fixture
def file_content(request):
    with open(request.param, "r") as f:
        return f.read()


@pytest.fixture
def base_expected_pairs(request):
    test_file_path = Path(request.module.__file__)
    sibling_directory_path = test_file_path.parent / "examples"

    expected = [
        str(item)
        for item in sibling_directory_path.iterdir()
        if item.name.endswith("_expected.py")
    ]
    base = [x.replace("_expected.py", ".py") for x in expected]

    return zip(base, expected)


def test_file_content(base_expected_pairs):
    for base, expected in base_expected_pairs:
        auto_wandb(base)
        fixed_name = base.replace(".py", "_wandb_logging.py")
        run_black(fixed_name)

        with open(fixed_name) as f:
            fixed = f.read()

        with open(expected) as f:
            expected = f.read()

        assert fixed == expected
