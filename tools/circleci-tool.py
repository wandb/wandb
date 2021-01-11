#!/usr/bin/env python

import argparse
import os
import subprocess

import requests

CIRCLECI_API_TOKEN = "CIRCLECI_TOKEN"

parser = argparse.ArgumentParser()
parser.add_argument("--platform", help="comma separated platform (linux,mac,win)")
parser.add_argument("--toxenv", help="single toxenv (py27,py36,py37,py38,py39)")
parser.add_argument("--test-file", help="test file (ex: tests/test.py)")
parser.add_argument("--test-name", help="test name (ex: test_dummy)")
parser.add_argument("--repeat", type=int, help="repeat N times (ex: 3)")
parser.add_argument("--dryrun", action="store_true", help="Dont do anything")
args = parser.parse_args()

platforms_dict = dict(linux="test", mac="mac", win="win")
py_name_dict = dict(py27="Python 2.7", py36="Python 3.6", py37="Python 3.7", py38="Python 3.8", py39="Python 3.9")
py_image_dict = dict(py27="python:2.7", py36="python:3.6", py37="python:3.7", py38="python:3.8", py39="python:3.9")


def req():
    api_token = os.environ.get(CIRCLECI_API_TOKEN)
    assert api_token, "Set environment variable: {}".format(CIRCLECI_API_TOKEN)
    url = "https://circleci.com/api/v2/project/gh/wandb/client/pipeline"
    code, branch = subprocess.getstatusoutput("git branch --show-current")
    assert code == 0, "failed git command"
    payload = {
        "branch": branch,
    }
    manual: bool = any([args.platform, args.toxenv, args.test_file, args.test_name, args.repeat])
    if manual:
        parameters = {"manual": True}
        platforms = args.platform.split(",") if args.platform else ["linux"]
        toxenv = args.toxenv or "py37"
        toxcmd = toxenv
        if args.test_file or args.repeat:
            toxcmd += " --"
        if args.test_file:
            toxcmd += " " + args.test_file
            if args.test_name:
                toxcmd += " -k " + args.test_name
        if args.repeat:
            toxcmd += " --flake-finder --flake-runss={}".format(args.repeat)
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
            # "manual_test_toxenv": "py38 -- tests/test_sender.py -k test_save_end_write_after_policy --flake-finder --flake-runs=5"
        payload["parameters"] = parameters
    print("Sending to CircleCI:", payload)
    if args.dryrun:
        return
    r = requests.post(url, json=payload, auth=(api_token, ""))
    assert r.status_code == 201, "Error making api requeest"
    d = r.json()
    num = d["number"]
    print("CircleCI workflow started:", num)


def main():
    req()


if __name__ == "__main__":
    main()
