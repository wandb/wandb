"""
This script collects and returns test file paths for a given root directory.

It uses pytest to discover test files, ignoring specified paths. The script
takes a root directory and optional ignore paths as command-line arguments.

The collected test file paths are printed to stdout, which can be useful
for integration with CI/CD pipelines or other automated testing processes.

Example usage:
    python get_test_files.py \
        /path/to/search \
        /path/to/search/ignore1 ...

This will collect all test files in '/path/to/search',
ignoring '/path/to/ignore1' and '/path/to/search/ignore1', and print
the paths of the collected test files to stdout.
"""

import contextlib
import os
import sys

import pytest


def collect_test_files():
    root = sys.argv[1]
    ignore_paths = sys.argv[2:]

    args = [
        "--collect-only",
        "-qq",
        root,
    ]
    for ignore_path in ignore_paths:
        args.append(f"--ignore={ignore_path}")

    class TestCollector:
        def __init__(self):
            self.paths = set()

        def pytest_collection_finish(self, session):
            for test in session.items:
                if type(test.parent) is pytest.Module:
                    self.paths.add(str(test.parent.nodeid))

    collector_plugin = TestCollector()

    # Do no write output from pytest collection.
    # Which would interfere with CircleCI reading from stdout.
    with contextlib.redirect_stdout(open(os.devnull, "w")):
        pytest.main(args, [collector_plugin])

    return collector_plugin.paths


if __name__ == "__main__":
    test_paths = collect_test_files()
    print(" ".join(test_paths))
