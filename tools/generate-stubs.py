"""What.

- Define high-level function in __init__.pyi.template
- Create __init__.pyi using the template substituting
  the docstrings from corresponding places in the source code.
- Check that the signature of the function in __init__.pyi
    matches the signature of the function in the source code.
"""

import pathlib


def main() -> None:
    path = pathlib.Path(__file__).parent.parent / "wandb"
    template = (path / "__init__.pyi.template").read_text()

    with open(path / "__init__.pyi", "w") as f:
        f.write(template)


if __name__ == "__main__":
    main()
