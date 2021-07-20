#!/usr/bin/env python
"""Tool to interract with CircleCI jobs using API key.

Get the current status of a circleci pipeline based on branch/commit
    ```
    $ ./circleci-tool status
    $ ./circleci-tool status --wait
    ```

Trigger (re)execution of a branch
    ```
    $ ./circleci-tool trigger
    $ ./circleci-tool trigger --wait
    $ ./circleci-tool trigger --platform mac
    $ ./circleci-tool trigger --platform mac --test-file tests/test.py
    $ ./circleci-tool trigger --platform win --test-file tests/test.py --test-name test_this
    $ ./circleci-tool trigger --platform win --test-file tests/test.py --test-name test_this --test-repeat 4
    $ ./circleci-tool trigger --toxenv py36,py37 --loop 3
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

platforms_dict = dict(linux="test", lin="test", mac="mac", win="win")
platforms_short_dict = dict(linux="lin", lin="lin", mac="mac", win="win")
py_name_dict = dict(py27="py27", py36="py36", py37="py37", py38="py38", py39="py39",)
py_image_dict = dict(
    py27="python:2.7",
    py36="python:3.6",
    py37="python:3.7",
    py38="python:3.8",
    py39="python:3.9",
)


def poll(args, pipeline_id=None, workflow_ids=None):
    print("Waiting for pipeline to complete (Branch: {})...".format(args.branch))
    while True:
        num = 0
        done = 0
        if pipeline_id:
            url = "https://circleci.com/api/v2/pipeline/{}/workflow".format(pipeline_id)
            r = requests.get(url, auth=(args.api_token, ""))
            assert r.status_code == 200, "Error making api request: {}".format(r)
            d = r.json()
            workflow_ids = [item["id"] for item in d["items"]]
        num = len(workflow_ids)
        for work_id in workflow_ids:
            work_status_url = "https://circleci.com/api/v2/workflow/{}".format(work_id)
            r = requests.get(work_status_url, auth=(args.api_token, ""))
            # print("STATUS", work_status_url)
            assert r.status_code == 200, "Error making api work request: {}".format(r)
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
    url = "https://circleci.com/api/v2/project/gh/wandb/client/pipeline"
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
            toxcmd += " --flake-finder --flake-runs={}".format(args.test_repeat)
        pyname = py_name_dict.get(toxenv)
        assert pyname, "unknown toxenv: {}".format(toxenv)
        pyimage = py_image_dict.get(toxenv)
        assert pyimage, "unknown toxenv: {}".format(toxenv)
        pyname = py_name_dict[toxenv]
        for p in platforms:
            job = platforms_dict.get(p)
            assert job, "unknown platform: {}".format(p)
            pshort = platforms_short_dict.get(p)
            jobname = "{}-{}".format(pshort, pyname)
            parameters["manual_" + job] = True
            parameters["manual_" + job + "_name"] = jobname
            if job == "test":
                parameters["manual_" + job + "_image"] = pyimage
            parameters["manual_" + job + "_toxenv"] = toxcmd
        payload["parameters"] = parameters
    print("Sending to CircleCI:", payload)
    if args.dryrun:
        return
    r = requests.post(url, json=payload, auth=(args.api_token, ""))
    assert r.status_code == 201, "Error making api requeest"
    d = r.json()
    uuid = d["id"]
    print("CircleCI workflow started:", uuid)
    if args.wait or args.loop:
        poll(args, pipeline_id=uuid)


def get_ci_builds(args, completed=True):
    bname = args.branch
    # TODO: extend pagination if not done
    url = "https://circleci.com/api/v1.1/project/gh/wandb/client?shallow=true&limit=100"
    if completed:
        url = url + "&filter=completed"
    # print("SEND", url)
    r = requests.get(url, auth=(args.api_token, ""))
    assert r.status_code == 200, "Error making api request: {}".format(r)
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
    # curl -H "Circle-Token: $CIRCLECI_TOKEN" https://circleci.com/api/v1.1/project/github/wandb/client/61238/artifacts
    # curl -L  -o out.dat -H "Circle-Token: $CIRCLECI_TOKEN" https://61238-86031674-gh.circle-artifacts.com/0/cover-results/.coverage
    cachedir = ".circle_cache"
    cfbase = "cover-{}-{}.xml".format(vhash, bnum)
    cfname = os.path.join(cachedir, cfbase)
    if not os.path.exists(cachedir):
        os.mkdir(cachedir)
    if os.path.exists(cfname):
        return
    url = "https://circleci.com/api/v1.1/project/github/wandb/client/{}/artifacts".format(
        bnum
    )
    r = requests.get(url, auth=(args.api_token, ""))
    assert r.status_code == 200, "Error making api request: {}".format(r)
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
            'curl -L  -o out.dat -H "Circle-Token: {}" "{}"'.format(args.api_token, u)
        )
        assert s == 0
        os.rename("out.dat", cfname)


def status(args):
    # TODO: check for current git hash only
    got = get_ci_builds(args, completed=False)
    if not got:
        print("ERROR: couldnt find job, maybe we should poll?")
        sys.exit(1)
    work_ids = [workid for _, _, _, workid in got]
    poll(args, workflow_ids=[work_ids[0]])


def download(args):
    print("Checking for circle artifacts (Branch: {})...".format(args.branch))
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
    parser.add_argument("--dryrun", action="store_true", help="Dont do anything")

    parse_trigger = subparsers.add_parser("trigger")
    parse_trigger.add_argument(
        "--platform", help="comma separated platform (linux,mac,win)"
    )
    parse_trigger.add_argument(
        "--toxenv", help="single toxenv (py27,py36,py37,py38,py39)"
    )
    parse_trigger.add_argument("--test-file", help="test file (ex: tests/test.py)")
    parse_trigger.add_argument("--test-name", help="test name (ex: test_dummy)")
    parse_trigger.add_argument("--test-repeat", type=int, help="repeat N times (ex: 3)")
    parse_trigger.add_argument("--loop", type=int, help="Outer loop (implies wait)")
    parse_trigger.add_argument(
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
    assert api_token, "Set environment variable: {}".format(CIRCLECI_API_TOKEN)
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
                print("Loop: {} of {}".format(i + 1, args.loop))
            trigger(args)
    elif args.action == "status":
        # find my workflow report status, wait on it (if specified)
        status(args)
    elif args.action == "download":
        download(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
