#!/usr/bin/env python3
import subprocess
import sys


def build_and_run_pex():
    # get current git branch
    current_branch = subprocess.check_output(
        ["git", "branch", "--show-current"],
        text=True,
    ).strip()

    executable = sys.executable
    commands = [
        {
            "command": [executable, "-m", "pip", "install", "pex"],
        },
        # {
        #     "command": ["sed", "-i", "-e", f"s/main/{current_branch}/g", "requirements.txt"],
        # },
        {
            "command": [
                "pex",
                ".",
                "-r",
                "requirements.txt",
                "-c",
                "main.py",
                "-o",
                "test.pex",
            ],
        },
        {
            "command": ["./test.pex"],
        },
        # {
        #     "command": ["sed", "-i", "-e", f"s/{current_branch}/main/g", "requirements.txt"],
        # },
    ]
    for cmd in commands:
        subprocess.run(cmd["command"], cwd=cmd.get("cwd", "."))


if __name__ == "__main__":
    build_and_run_pex()
