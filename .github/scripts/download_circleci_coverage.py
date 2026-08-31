"""Downloads a CircleCI job's coverage artifacts for upload to Datadog.

Invoked by the datadog-coverage workflow with TARGET_URL set to the
CircleCI job link from the commit status. Downloads the job's
coverage-reports/<flags>/* artifacts and emits `flags` and `reports-dir`
step outputs for DataDog/coverage-upload-github-action. Each job stores
reports under a single flags group, so finding more than one is an error.
"""

# ruff: noqa: T201 (allow print())

import json
import os
import pathlib
import re
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


def _set_output(name: str, value: str) -> None:
    with open(os.environ["GITHUB_OUTPUT"], "a") as f:
        f.write(f"{name}={value}\n")


def main() -> int:
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

    if len(by_flags) > 1:
        print(f"Expected one flags group per job, found {sorted(by_flags)}.")
        return 1

    ((flags, artifacts),) = by_flags.items()
    reports_dir = pathlib.Path("coverage-reports", flags)
    for artifact in artifacts:
        node_dir = reports_dir / str(artifact["node_index"])
        node_dir.mkdir(parents=True, exist_ok=True)
        print(f"Downloading {artifact['path']} from node {artifact['node_index']}")
        name = artifact["path"].rsplit("/", 1)[-1]
        urllib.request.urlretrieve(artifact["url"], node_dir / name)

    _set_output("flags", flags)
    _set_output("reports-dir", str(reports_dir))
    return 0


if __name__ == "__main__":
    sys.exit(main())
