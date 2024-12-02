import contextlib
import os
from datetime import datetime

import click


@click.command()
@click.option(
    "--version",
    required=True,
    help="The version being released.",
)
def main(version: str):
    """Update CHANGELOG files for a new release."""
    changes = _cut_unreleased()
    _insert_changelog(version=version, changes=changes)


def _cut_unreleased() -> str:
    """Cut the "Unreleased" section from CHANGELOG.unreleased.md.

    Returns:
        The "Unreleased" section as a string.
    """
    with open("CHANGELOG.unreleased.md") as f:
        lines = f.readlines()
        start_line = lines.index("## Unreleased\n") + 1

    with open("CHANGELOG.unreleased.md", "w") as f:
        f.writelines(lines[:start_line])

    return "".join(lines[start_line:])


def _insert_changelog(*, version: str, changes: str):
    """Insert a new section into CHANGELOG.md."""
    date = datetime.now().strftime("%Y-%m-%d")

    with contextlib.ExitStack() as stack:
        changelog_in = stack.enter_context(open("CHANGELOG.md"))
        changelog_out = stack.enter_context(open("CHANGELOG.md.tmp", "w"))

        while line := changelog_in.readline():
            changelog_out.writelines([line])

            if "tools/changelog.py: insert here" in line:
                changelog_out.writelines(
                    [
                        "\n",
                        f"## [{version}] - {date}\n",
                        changes,
                    ]
                )

    os.unlink("CHANGELOG.md")
    os.rename("CHANGELOG.md.tmp", "CHANGELOG.md")


if __name__ == "__main__":
    main()
