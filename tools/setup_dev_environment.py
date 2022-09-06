#!/usr/bin/env python3

import argparse
import platform
import re
import subprocess
import sys

from pkg_resources import parse_version

PYTHON_VERSIONS = ["3.6", "3.7", "3.8", "3.9", "3.10"]
TOX_VERSION = "3.24.0"


# Python 3.6 is not installable on Macs with Apple silicon
if platform.system() == "Darwin" and platform.processor() == "arm":
    PYTHON_VERSIONS.pop(0)


class Console:
    BOLD = "\033[1m"
    CODE = "\033[2m"
    MAGENTA = "\033[95m"
    BLUE = "\033[94m"
    CYAN = "\033[96m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    END = "\033[0m"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-p",
        "--python-versions",
        nargs="+",
        help="Python versions to use with pyenv.",
    )

    args = parser.parse_args()
    python_versions = args.python_versions

    if python_versions is None:
        python_versions = PYTHON_VERSIONS
    else:
        invalid_versions = [v for v in python_versions if v not in PYTHON_VERSIONS]
        if invalid_versions:
            print(
                f"Requested invalid python versions: {invalid_versions}.\n"
                f"Please select from {PYTHON_VERSIONS}."
            )
            sys.exit(1)

    print(f"{Console.BLUE}Configuring test environment...{Console.END}")

    # installed pyenv versions
    p = subprocess.run(
        ["pyenv", "versions"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    existing_python_versions = set(
        re.findall(r"[*]*\s([\d.]+)", p.stdout.decode("utf-8"))
    )

    p = subprocess.run(
        ["pyenv", "install", "--list"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    all_available_python_versions = re.findall(
        r"\s\s([\d.]+)\n", p.stdout.decode("utf-8")
    )

    installed_python_versions = []
    for python_version in python_versions:
        available_python_versions = [
            v for v in all_available_python_versions if v.startswith(python_version)
        ]
        latest = max(available_python_versions, key=parse_version)
        install_command = ["pyenv", "install", "-s", latest]
        stdin = subprocess.PIPE

        # Python 3.6 on MacOS > 11.2 needs a patch that works up to 3.6.13
        is_3_6_and_macos_gt_11_2 = (
            python_version == "3.6"
            and platform.system() == "Darwin"
            and parse_version(platform.mac_ver()[0]) > parse_version("11.2")
        )
        if is_3_6_and_macos_gt_11_2:
            latest = "3.6.13"
            patch = subprocess.Popen(
                [
                    "curl",
                    "-sSL",
                    "https://github.com/python/cpython/commit/8ea6353.patch",
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
            install_command = [
                "pyenv",
                "install",
                "--patch",
                latest,
            ]
            stdin = patch.stdout

        if latest in existing_python_versions:
            print(f"Already installed: {latest}")
        else:
            print(f"Installing: {latest}...")
            p = subprocess.run(
                install_command,
                stdin=stdin,
                stdout=sys.stdout,
                stderr=subprocess.STDOUT,
            )
            if p.returncode != 0:
                print(f"Failed to install {latest}")
        installed_python_versions.append(latest)

    print(f"Setting local pyenv versions to: {' '.join(installed_python_versions)}")
    subprocess.run(
        ["pyenv", "local", *installed_python_versions],
        stdout=sys.stdout,
        stderr=subprocess.STDOUT,
        check=True,
    )

    print("Installing dependencies: tox...")
    subprocess.run(
        ["python", "-m", "pip", "install", "-qq", f"tox=={TOX_VERSION}"],
        stdout=sys.stdout,
        stderr=subprocess.STDOUT,
        check=True,
    )

    print(f"{Console.GREEN}Development environment setup!{Console.END}")
    print()
    print("Run all tests in all python environments:")
    print(f"{Console.CODE}  tox{Console.END}")
    print("Run a specific test in a specific environment:")
    print(
        f"{Console.CODE}  tox -e py37 -- tests/test_public_api.py -k test_run_config{Console.END}"
    )
    print("Lint code:")
    print(f"{Console.CODE}  tox -e format,flake8,mypy{Console.END}")


if __name__ == "__main__":
    main()
