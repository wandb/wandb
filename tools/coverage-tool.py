#!/usr/bin/env python
"""Helper for codecov at wandb.

First run the following to install the circleci tool:
    curl -fLSs https://circle.ci/cli | bash

Usage:
    ./tools/coverage-tool.py jobs
    ./tools/coverage-tool.py check
"""

import argparse
import configparser
import re
import subprocess
import sys

import yaml


def find_list_of_key_locations_and_dicts(data, search_key: str, root=None):
    """Search for a dict with key search_key and value containing search_v.

    Returns:
       # location - list of indexes representing where to find the key
       # containing_dict - the dictionary where the search_key was found
       List of tuples of the form: (location, containing_dict)
    """
    found = []
    if root is None:
        root = []
    if isinstance(data, list):
        for num, val in enumerate(data):
            find_root = root[:]
            find_root.append(num)
            found.extend(
                find_list_of_key_locations_and_dicts(val, search_key, root=find_root)
            )
    elif isinstance(data, dict):
        check = data.get(search_key)
        if check:
            found.append((root, data))
        for key, val in data.items():
            find_root = root[:]
            find_root.append(key)
            found.extend(
                find_list_of_key_locations_and_dicts(val, search_key, root=find_root)
            )
    elif isinstance(data, (str, int, float, type(None))):
        pass
    else:
        raise RuntimeError(f"unknown type: type={type(data)} data={data}")
    return found


def coverage_config_check(jobs_count, codecov_yaml):
    with open(codecov_yaml) as file:
        data = yaml.safe_load(file)
        num_builds_tuple_list = find_list_of_key_locations_and_dicts(
            data, "after_n_builds"
        )
        for _, data in num_builds_tuple_list:
            num_builds = data["after_n_builds"]
            if num_builds != jobs_count:
                print(f"Mismatch builds count: {num_builds} (expecting {jobs_count})")
                sys.exit(1)


def coveragerc_file_check(tox_envs, coveragerc):
    cf = configparser.ConfigParser()
    cf.read(coveragerc)

    paths = cf.get("paths", "canonicalsrc").split()

    # lets generate what paths should look like
    expected_paths = ["wandb/"]
    for tox_env in sorted(tox_envs):
        modified_toxenv = tox_env.split("-")
        py_version = modified_toxenv[-1]
        modified_toxenv.pop(1)
        modified_toxenv = "-".join(modified_toxenv)
        assert py_version.startswith("py")
        python = "".join(("python", py_version[2], ".", py_version[3:]))

        path = f".tox/{modified_toxenv}/lib/{python}/site-packages/wandb/"
        expected_paths.append(path)

    if paths != expected_paths:
        print("Mismatch .coveragerc!\nSeen:")
        for path in paths:
            print(f"\t{path}")
        print("Expected:")
        for path in expected_paths:
            print(f"\t{path}")
        sys.exit(1)


def find_num_coverage_jobs(circleci_yaml):
    config_process = subprocess.run(
        f"circleci config process {circleci_yaml}",
        shell=True,
        stdout=subprocess.PIPE,
        check=True,
    )
    config_yaml = yaml.safe_load(config_process.stdout)

    jobs = {}
    for job_name, job_config in config_yaml["jobs"].items():
        parallelism = job_config.get("parallelism", 1)
        if "steps" in job_config:
            for step in job_config["steps"][1:]:
                if "run" in step and re.search(
                    "cover-.*-circle", step["run"]["command"]
                ):
                    jobs[job_name] = parallelism
    return jobs


def process_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--circleci-yaml", default=".circleci/config.yml")
    parser.add_argument("--codecov-yaml", default=".codecov.yml")
    parser.add_argument("--coveragerc", default=".coveragerc")

    subparsers = parser.add_subparsers(
        dest="action", title="action", description="Action to perform"
    )
    subparsers.add_parser("jobs")
    subparsers.add_parser("check")

    args = parser.parse_args()
    return parser, args


def print_coverage_jobs(args):
    tasks = find_num_coverage_jobs(args.circleci_yaml)
    max_key_len = max(len(t) for t in tasks)
    for k, v in tasks.items():
        print(f"{k:{max_key_len}} {v}")
    print("-" * (max_key_len + 1 + 3))
    print(f"{'Total':{max_key_len}} {sum(tasks.values())}")


def check_coverage(args):
    tasks = find_num_coverage_jobs(args.circleci_yaml)
    # let's only count the main workflow
    num_tasks = sum(tasks.values())
    func_tasks = filter(lambda x: x.startswith("func-"), tasks.keys())
    coverage_config_check(num_tasks, args.codecov_yaml)
    coveragerc_file_check(func_tasks, args.coveragerc)
    print("All checks passed!")


def main():
    parser, args = process_args()
    if args.action == "jobs":
        print_coverage_jobs(args)
    elif args.action == "check":
        check_coverage(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
