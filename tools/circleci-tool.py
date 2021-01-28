#!/usr/bin/env python
"""Trigger CircleCI runs using API key."""

import argparse
import os
import subprocess
import time

import requests

CIRCLECI_API_TOKEN = "CIRCLECI_TOKEN"

parser = argparse.ArgumentParser()
parser.add_argument("--platform", help="comma separated platform (linux,mac,win)")
parser.add_argument("--toxenv", help="single toxenv (py27,py36,py37,py38,py39)")
parser.add_argument("--test-file", help="test file (ex: tests/test.py)")
parser.add_argument("--test-name", help="test name (ex: test_dummy)")
parser.add_argument("--test-repeat", type=int, help="repeat N times (ex: 3)")
parser.add_argument("--branch", help="git branch (autodetected)")
parser.add_argument("--dryrun", action="store_true", help="Dont do anything")
parser.add_argument("--wait", action="store_true", help="Wait for finish or error")
parser.add_argument("--loop", type=int, help="Outer loop (implies wait)")
parser.add_argument("--wait-workflow", help="Wait for workflow")
args = parser.parse_args()

platforms_dict = dict(linux="test", mac="mac", win="win")
py_name_dict = dict(py27="Python 2.7", py36="Python 3.6", py37="Python 3.7", py38="Python 3.8", py39="Python 3.9")
py_image_dict = dict(py27="python:2.7", py36="python:3.6", py37="python:3.7", py38="python:3.8", py39="python:3.9")

api_token = os.environ.get(CIRCLECI_API_TOKEN)
assert api_token, "Set environment variable: {}".format(CIRCLECI_API_TOKEN)

branch = args.branch
if not branch:
    code, branch = subprocess.getstatusoutput("git branch --show-current")
    assert code == 0, "failed git command"


def poll(num):
    print("Waiting for pipeline to complete...")
    url = "https://circleci.com/api/v2/pipeline/{}/workflow".format(num)
    while True:
        r = requests.get(url, auth=(api_token, ""))
        assert r.status_code == 200, "Error making api request: {}".format(r)
        d = r.json()
        done = 0
        num = len(d["items"])
        for item in d["items"]:
            work_id = item["id"]
            work_status_url = "https://circleci.com/api/v2/workflow/{}".format(work_id)
            r = requests.get(work_status_url, auth=(api_token, ""))
            assert r.status_code == 200, "Error making api work request: {}".format(r)
            w = r.json()
            status = w["status"]
            print("Status:", status)
            if status != "running":
                done += 1
        if num and done == num:
            print("Finished")
            return
        time.sleep(20)


def req():
    url = "https://circleci.com/api/v2/project/gh/wandb/client/pipeline"
    payload = {
        "branch": branch,
    }
    manual: bool = any([args.platform, args.toxenv, args.test_file, args.test_name, args.test_repeat])
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
            parameters["manual_" + job] = True
            parameters["manual_" + job + "_name"] = pyname
            if job == "test":
                parameters["manual_" + job + "_image"] = pyimage
            parameters["manual_" + job + "_toxenv"] = toxcmd
        payload["parameters"] = parameters
    print("Sending to CircleCI:", payload)
    if args.dryrun:
        return
    r = requests.post(url, json=payload, auth=(api_token, ""))
    assert r.status_code == 201, "Error making api requeest"
    d = r.json()
    uuid = d["id"]
    print("CircleCI workflow started:", uuid)
    if args.wait or args.loop:
        poll(uuid)


def main():
    if args.wait_workflow:
        poll(args.wait_workflow)
        return

    for i in range(args.loop or 1):
        if args.loop:
            print("Loop: {} of {}".format(i + 1, args.loop))
        req()


if __name__ == "__main__":
    main()
