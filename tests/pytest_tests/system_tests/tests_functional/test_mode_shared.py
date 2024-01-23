import pathlib
import runpy
from unittest import mock


def test_mode_shared(user, copy_asset):
    # copy assets to test directory:
    pathlib.Path("scripts").mkdir()
    pathlib.Path(".wandb").mkdir()
    for script in ("train.py", "eval.py"):
        copy_asset(pathlib.Path("scripts") / script)

    # # Run the script with the specified globals
    path = str(pathlib.Path("scripts") / "train.py")
    # clear argv
    with mock.patch("sys.argv", [""]):
        output_namespace = runpy.run_path(path, run_name="__main__")
        print(output_namespace)
