import os
import pathlib

CONFIG = {
    "include": [
        "functional_tests",
        "standalone_tests",
        "tests",
        "tools",
        "wandb",
    ],
    "exclude": [
        os.path.join("wandb", "proto"),
        os.path.join("wandb", "vendor"),
        os.path.join("tests", "logs"),
    ],
    "exclude_unrooted": [
        os.path.join("wandb", "run-"),
        os.path.join("wandb", "offline-run-"),
    ],
}


def locate_py_files(root_path: pathlib.Path):
    """
    Recursively search for Python files in the given root directory.
    """
    include = {root_path / dir_path for dir_path in CONFIG["include"]}
    exclude = {root_path / dir_path for dir_path in CONFIG["exclude"]}
    exclude_unrooted = CONFIG["exclude_unrooted"]
    for path in map(str, root_path.rglob("*.py")):
        if (
            any(
                path.startswith(str(root_path / dir_path))
                for dir_path in map(pathlib.Path.absolute, include)
            )
            and all(
                not path.startswith(str(root_path / dir_path))
                for dir_path in map(pathlib.Path.absolute, exclude)
            )
            and all(dir_path not in path for dir_path in exclude_unrooted)
        ):
            print(path)


if __name__ == "__main__":
    repo_root_path = pathlib.Path.absolute(pathlib.Path(__file__).parent.parent)
    locate_py_files(repo_root_path)
