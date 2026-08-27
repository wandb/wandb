"""Uploads a CircleCI job's coverage artifacts to Datadog Code Coverage.

Invoked by the datadog-coverage workflow with TARGET_URL set to the
CircleCI job link from the commit status. Downloads the job's
coverage-reports/<flags>/* artifacts and runs `datadog-ci coverage upload`
once per flags group. Requires DD_API_KEY and the DD_GIT_* variables; the
git metadata itself comes from Datadog's GitHub integration.
"""

# ruff: noqa: T201 (allow print())

import json
import os
import pathlib
import re
import subprocess
import sys
import urllib.request

_ARTIFACTS_URL = "https://circleci.com/api/v2/project/gh/wandb/wandb/{}/artifacts"


def _list_artifacts(job_number: str) -> list[dict]:
    artifacts = []
    page_token = ""
    while True:
        url = _ARTIFACTS_URL.format(job_number)
        if page_token:
            url += f"?page-token={page_token}"
        with urllib.request.urlopen(url) as response:
            page = json.load(response)
        artifacts += page["items"]
        page_token = page.get("next_page_token")
        if not page_token:
            return artifacts


def main() -> int:
    if not os.environ.get("DD_API_KEY"):
        print("DD_API_KEY is not set; skipping coverage upload.")
        return 0

    target_url = os.environ["TARGET_URL"]
    match = re.search(r"/(\d+)(?:\?|$)", target_url)
    if not match:
        print(f"Could not parse a CircleCI job number from {target_url!r}.")
        return 1
    job_number = match.group(1)

    by_flags: dict[str, list[dict]] = {}
    for artifact in _list_artifacts(job_number):
        flags = re.search(r"coverage-reports/([^/]+)/", artifact["path"])
        if flags:
            by_flags.setdefault(flags.group(1), []).append(artifact)

    if not by_flags:
        print(f"No coverage reports in CircleCI job {job_number}; nothing to do.")
        return 0

    for flags, artifacts in sorted(by_flags.items()):
        reports_dir = pathlib.Path("coverage-reports", flags)
        for artifact in artifacts:
            # Parallel job nodes store identically-named reports.
            node_dir = reports_dir / str(artifact["node_index"])
            node_dir.mkdir(parents=True, exist_ok=True)
            print(f"Downloading {artifact['path']} from node {artifact['node_index']}")
            name = artifact["path"].rsplit("/", 1)[-1]
            urllib.request.urlretrieve(artifact["url"], node_dir / name)

        command = [
            "datadog-ci",
            "coverage",
            "upload",
            # Datadog's GitHub integration provides git metadata, and the
            # checkout here is the default branch, not the covered commit.
            "--skip-git-metadata-upload",
            "--disable-file-fixes",
            "--flags",
            flags,
            str(reports_dir),
        ]
        if os.environ.get("DRY_RUN"):
            command.append("--dry-run")
        subprocess.run(command, check=True)

    return 0


if __name__ == "__main__":
    sys.exit(main())
