#!/usr/bin/env python
"""Tool to interact with CircleCI jobs using API key.

Get the current status of a circleci pipeline based on branch/commit
    ```
    $ ./circleci-tool status
    $ ./circleci-tool status --wait
    ```

Trigger (re)execution of a branch
    ```
    $ ./circleci-tool.py trigger
    $ ./circleci-tool.py trigger --wait
    $ ./circleci-tool.py trigger --platform mac
    $ ./circleci-tool.py trigger --platform mac --test-file tests/test.py
    $ ./circleci-tool.py trigger --platform win --test-file tests/test.py --test-name test_this
    $ ./circleci-tool.py trigger --platform win --test-file tests/test.py --test-name test_this --test-repeat 4
    $ ./circleci-tool.py trigger --toxenv py36,py37 --loop 3
    $ ./circleci-tool.py trigger --wait --platform win --test-file tests/test_notebooks.py --parallelism 5 --xdist 2
    $ ./circleci-tool.py trigger --toxenv func-s_service-py37 --loop 3

    ```

Trigger nightly run
    ```
    $ ./circleci-tool.py trigger-nightly --slack-notify
    ```

Download artifacts from an executed workflow
    ```
    $ ./circleci-tool download
    ```

"""


import argparse
import os
import subprocess
import sys
import time

import requests

CIRCLECI_API_TOKEN = "CIRCLECI_TOKEN"

NIGHTLY_SHARDS = (
    "standalone-cpu",
    "standalone-gpu",
    "standalone-tpu",
    "standalone-local",
    "kfp",
    "standalone-gpu-win",
)

platforms_dict = dict(linux="test", lin="test", mac="mac", win="win")
platforms_short_dict = dict(linux="lin", lin="lin", mac="mac", win="win")
py_name_dict = dict(
    py36="py36",
    py37="py37",
    py38="py38",
    py39="py39",
)
py_image_dict = dict(
    py36="python:3.6",
    py37="python:3.7",
    py38="python:3.8",
    py39="python:3.9",
)


def poll(args, pipeline_id=None, workflow_ids=None):
    print(f"Waiting for pipeline to complete (Branch: {args.branch})...")
    while True:
        num = 0
        done = 0
        if pipeline_id:
            url = f"https://circleci.com/api/v2/pipeline/{pipeline_id}/workflow"
            r = requests.get(url, auth=(args.api_token, ""))
            assert r.status_code == 200, f"Error making api request: {r}"
            d = r.json()
            workflow_ids = [item["id"] for item in d["items"]]
        num = len(workflow_ids)
        for work_id in workflow_ids:
            work_status_url = f"https://circleci.com/api/v2/workflow/{work_id}"
            r = requests.get(work_status_url, auth=(args.api_token, ""))
            # print("STATUS", work_status_url)
            assert r.status_code == 200, f"Error making api work request: {r}"
            w = r.json()
            status = w["status"]
            print("Status:", status)
            if status not in ("running", "failing"):
                done += 1
        if num and done == num:
            print("Finished")
            return
        time.sleep(20)


def trigger(args):
    url = "https://circleci.com/api/v2/project/gh/wandb/wandb/pipeline"
    payload = {
        "branch": args.branch,
    }
    manual: bool = any(
        [args.platform, args.toxenv, args.test_file, args.test_name, args.test_repeat]
    )
    if manual:
        parameters = {"manual": True}
        platforms = args.platform.split(",") if args.platform else ["linux"]
        toxenv = args.toxenv or "py37"
        toxcmd = toxenv
        if args.test_file or args.test_repeat:
            toxcmd += " --"
        if args.test_file:
            toxcmd += " " + args.test_file
            if args.test_name:
                toxcmd += " -k " + args.test_name
        if args.test_repeat:
            toxcmd += f" --flake-finder --flake-runs={args.test_repeat}"
        # get last token split by hyphen as python version
        pyver = toxenv.split("-")[-1]
        pyname = py_name_dict.get(pyver)
        assert pyname, f"unknown pyver: {pyver}"
        # handle more complex pyenv (func tests)
        if pyver != toxenv:
            toxsplit = toxenv.split("-")
            assert len(toxsplit) == 3
            tsttyp, tstshard, tstver = toxsplit
            prefix = "s_"
            if tstshard.startswith(prefix):
                tstshard = tstshard[len(prefix) :]
            pyname = f"{pyname}-{tsttyp}-{tstshard}"
        pyimage = py_image_dict.get(pyver)
        assert pyimage, f"unknown pyver: {pyver}"
        for p in platforms:
            job = platforms_dict.get(p)
            assert job, f"unknown platform: {p}"
            pshort = platforms_short_dict.get(p)
            jobname = f"{pshort}-{pyname}"
            parameters["manual_" + job] = True
            parameters["manual_" + job + "_name"] = jobname
            if job == "test":
                parameters["manual_" + job + "_image"] = pyimage
            parameters["manual_" + job + "_toxenv"] = toxcmd
            if args.parallelism:
                parameters["manual_parallelism"] = args.parallelism
            if args.xdist:
                parameters["manual_xdist"] = args.xdist
        payload["parameters"] = parameters
    print("Sending to CircleCI:", payload)
    if args.dryrun:
        return
    r = requests.post(url, json=payload, auth=(args.api_token, ""))
    assert r.status_code == 201, "Error making api request"
    d = r.json()
    uuid = d["id"]
    print("CircleCI workflow started:", uuid)
    if args.wait or args.loop:
        poll(args, pipeline_id=uuid)


def trigger_nightly(args):
    url = "https://circleci.com/api/v2/project/gh/wandb/wandb/pipeline"

    default_shards = set(NIGHTLY_SHARDS)
    shards = {
        f"manual_nightly_execute_shard_{shard.replace('-', '_')}": False
        for shard in default_shards
    }

    requested_shards = set(args.shards.split(",")) if args.shards else default_shards

    # check that all requested shards are valid and that there is at least one
    if not requested_shards.issubset(default_shards):
        raise ValueError(
            f"Requested invalid shards: {requested_shards}. "
            f"Valid shards are: {default_shards}"
        )
    # flip the requested shards to True
    for shard in requested_shards:
        shards[f"manual_nightly_execute_shard_{shard.replace('-', '_')}"] = True

    payload = {
        "branch": args.branch,
        "parameters": {
            **{
                "manual": True,
                "manual_nightly": True,
                "manual_nightly_git_branch": args.branch,
                "manual_nightly_slack_notify": args.slack_notify or False,
            },
            **shards,
        },
    }

    print("Sending to CircleCI:", payload)
    if args.dryrun:
        return
    r = requests.post(url, json=payload, auth=(args.api_token, ""))
    assert r.status_code == 201, "Error making api request"
    d = r.json()
    uuid = d["id"]
    print("CircleCI workflow started:", uuid)
    if args.wait:
        poll(args, pipeline_id=uuid)


def get_ci_builds(args, completed=True):
    bname = args.branch
    # TODO: extend pagination if not done
    url = "https://circleci.com/api/v1.1/project/gh/wandb/wandb?shallow=true&limit=100"
    if completed:
        url = url + "&filter=completed"
    # print("SEND", url)
    r = requests.get(url, auth=(args.api_token, ""))
    assert r.status_code == 200, f"Error making api request: {r}"
    lst = r.json()
    cfirst = None
    ret = []
    done = False
    for d in lst:
        b = d.get("branch")
        if b != bname:
            continue
        v = d.get("vcs_revision")
        n = d.get("build_num")
        j = d.get("workflows", {}).get("job_name")
        w = d.get("workflows", {}).get("workflow_id")
        # print("DDD", d)
        cfirst = cfirst or v
        if cfirst != v:
            done = True
            break
        ret.append((v, n, j, w))
    if not done:
        return
    return ret


def grab(args, vhash, bnum):
    # curl -H "Circle-Token: $CIRCLECI_TOKEN" https://circleci.com/api/v1.1/project/github/wandb/wandb/61238/artifacts
    # curl -L  -o out.dat -H "Circle-Token: $CIRCLECI_TOKEN" https://61238-86031674-gh.circle-artifacts.com/0/cover-results/.coverage
    cachedir = ".circle_cache"
    cfbase = f"cover-{vhash}-{bnum}.xml"
    cfname = os.path.join(cachedir, cfbase)
    if not os.path.exists(cachedir):
        os.mkdir(cachedir)
    if os.path.exists(cfname):
        return
    url = (
        "https://circleci.com/api/v1.1/project/github/wandb/wandb/{}/artifacts".format(
            bnum
        )
    )
    r = requests.get(url, auth=(args.api_token, ""))
    assert r.status_code == 200, f"Error making api request: {r}"
    lst = r.json()
    if not lst:
        return
    for item in lst:
        p = item.get("path")
        u = item.get("url")
        # print("got", p)
        if p != "cover-results/coverage.xml":
            continue
        # print("GRAB", p, u)
        # TODO: use tempfile
        print("Downloading circle artifacts...")
        s, o = subprocess.getstatusoutput(
            f'curl -L  -o out.dat -H "Circle-Token: {args.api_token}" "{u}"'
        )
        assert s == 0
        os.rename("out.dat", cfname)


def status(args):
    # TODO: check for current git hash only
    got = get_ci_builds(args, completed=False)
    if not got:
        print("ERROR: couldn't find job, maybe we should poll?")
        sys.exit(1)
    work_ids = [workid for _, _, _, workid in got]
    poll(args, workflow_ids=[work_ids[0]])


def download(args):
    print(f"Checking for circle artifacts (Branch: {args.branch})...")
    got = get_ci_builds(args)
    assert got
    for v, n, _, _ in got:
        grab(args, v, n)


def process_args():
    parser = argparse.ArgumentParser()

    subparsers = parser.add_subparsers(
        dest="action", title="action", description="Action to perform"
    )
    parser.add_argument("--api_token", help=argparse.SUPPRESS)
    parser.add_argument("--branch", help="git branch (autodetected)")
    parser.add_argument("--dryrun", action="store_true", help="Don't do anything")

    parse_trigger = subparsers.add_parser("trigger")
    parse_trigger.add_argument(
        "--platform", help="comma-separated platform (linux,mac,win)"
    )
    parse_trigger.add_argument("--toxenv", help="single toxenv (py36,py37,py38,py39)")
    parse_trigger.add_argument("--test-file", help="test file (ex: tests/test.py)")
    parse_trigger.add_argument("--test-name", help="test name (ex: test_dummy)")
    parse_trigger.add_argument("--test-repeat", type=int, help="repeat N times (ex: 3)")
    parse_trigger.add_argument("--parallelism", type=int, help="CircleCI parallelism")
    parse_trigger.add_argument("--xdist", type=int, help="pytest xdist parallelism")
    parse_trigger.add_argument("--loop", type=int, help="Outer loop (implies wait)")
    parse_trigger.add_argument(
        "--wait", action="store_true", help="Wait for finish or error"
    )

    parse_trigger_nightly = subparsers.add_parser("trigger-nightly")
    parse_trigger_nightly.add_argument(
        "--slack-notify", action="store_true", help="post notifications to slack"
    )
    parse_trigger_nightly.add_argument(
        "--shards",
        default=",".join(NIGHTLY_SHARDS),
        help="comma-separated shards (standalone-{cpu,gpu,tpu,local,gpu-win},kfp)",
    )
    parse_trigger_nightly.add_argument(
        "--wait", action="store_true", help="Wait for finish or error"
    )

    parse_status = subparsers.add_parser("status")
    parse_status.add_argument(
        "--wait", action="store_true", help="Wait for finish or error"
    )

    parse_download = subparsers.add_parser("download")
    parse_download.add_argument(
        "--wait", action="store_true", help="Wait for finish or error"
    )

    args = parser.parse_args()
    return parser, args


def process_environment(args):
    api_token = os.environ.get(CIRCLECI_API_TOKEN)
    assert api_token, f"Set environment variable: {CIRCLECI_API_TOKEN}"
    args.api_token = api_token


def process_workspace(args):
    branch = args.branch
    if not branch:
        code, branch = subprocess.getstatusoutput("git branch --show-current")
        assert code == 0, "failed git command"
        args.branch = branch


def main():
    parser, args = process_args()
    process_environment(args)
    process_workspace(args)

    if args.action == "trigger":
        for i in range(args.loop or 1):
            if args.loop:
                print(f"Loop: {i + 1} of {args.loop}")
            trigger(args)
    elif args.action == "trigger-nightly":
        trigger_nightly(args)
    elif args.action == "status":
        # find my workflow report status, wait on it (if specified)
        status(args)
    elif args.action == "download":
        download(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
