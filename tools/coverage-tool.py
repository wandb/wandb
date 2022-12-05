#!/usr/bin/env python
"""Helper for codecov at wandb

Usage:
    ./tools/coverage-tool.py jobs
    ./tools/coverage-tool.py jobs | wc -l
    ./tools/coverage-tool.py check
"""

import argparse
import configparser
import copy
import itertools
import sys

import yaml


def find_list_of_key_locations_and_dicts(data, search_key: str, root=None):
    """Search for a dict with key search_key and value containing search_v

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
    elif isinstance(data, (str, int, float)):
        pass
    else:
        raise RuntimeError(f"unknown type: type={type(data)} data={data}")
    return found


def find_parallelism_defaults(loc_dict_tuple):
    _, containing_dict = loc_dict_tuple
    parallelism = containing_dict.get("parallelism")
    if not isinstance(parallelism, dict):
        return False
    default = parallelism.get("default")
    return isinstance(default, int) and default > 1


def matrix_expand(loc_dict_tuple_list):
    ret = []
    loc_dict_tuple_list = list(loc_dict_tuple_list)
    for location, containing_dict in loc_dict_tuple_list:
        matrix = containing_dict.get("matrix")
        if matrix:
            # assume any block referencing a matrix is using all parameters
            # could check <<>> and expand syntax
            parameters = matrix.get("parameters")
            groups = []
            for k, v in parameters.items():
                groups.append([(k, i) for i in v])

            product = itertools.product(*groups)
            product = list(product)
            for subs in product:
                data = copy.deepcopy(containing_dict)
                toxenv = data["toxenv"]
                for k, v in subs:
                    replace = f"<<matrix.{k}>>"
                    assert replace in toxenv, f"Cant find {replace} in {toxenv}"
                    toxenv = toxenv.replace(replace, str(v))
                data["toxenv"] = toxenv
                ret.append((location, data))
        else:
            ret.append((location, containing_dict))
    return ret


def create_parallelism_defaults_dict(par_defaults_list):
    ret = {}
    for location, containing_dict in par_defaults_list:
        assert len(location) == 3
        jobs, job_name, parameters = location
        assert jobs == "jobs"
        assert parameters == "parameters"
        default = containing_dict["parallelism"]["default"]
        ret[job_name] = default
    return ret


def parallelism_expand(cov_list, par_dict):
    ret = []
    for location, containing_dict in cov_list:
        parallelism = containing_dict.get("parallelism")
        if parallelism:
            count = parallelism
        else:
            # see if we can find counts in defaults
            # look up by last element in location
            lookup = location[-1]
            count = par_dict.get(lookup, 1)

        for i in range(count):
            loc = location[:]
            if count > 1:
                loc.append(i)
            ret.append((loc, containing_dict))
    return ret


def coverage_tasks(args: argparse.Namespace):

    ci_fname = args.circleci_yaml

    with open(ci_fname) as file:
        data = yaml.safe_load(file)

        parallelism = find_list_of_key_locations_and_dicts(data, "parallelism")
        parallelism_defaults = filter(find_parallelism_defaults, parallelism)
        toxenv = find_list_of_key_locations_and_dicts(data, "toxenv")
        toxenv_cov = filter(lambda x: "covercircle" in x[1]["toxenv"], toxenv)
        toxenv_cov_matrix = matrix_expand(toxenv_cov)
        par_default_dict = create_parallelism_defaults_dict(parallelism_defaults)
        toxenv_cov_matrix_parallelism = parallelism_expand(
            toxenv_cov_matrix, par_default_dict
        )
        tasks = [
            (".".join(map(str, x[0])), x[1]["toxenv"])
            for x in toxenv_cov_matrix_parallelism
        ]
    return tasks


def coverage_config_check(jobs_count, args):
    ci_fname = args.codecov_yaml

    with open(ci_fname) as file:
        data = yaml.safe_load(file)
        num_builds_tuple_list = find_list_of_key_locations_and_dicts(
            data, "after_n_builds"
        )
        for _, data in num_builds_tuple_list:
            num_builds = data["after_n_builds"]
            if num_builds != jobs_count:
                print(f"Mismatch builds count: {num_builds} (expecting {jobs_count})")
                sys.exit(1)


def coverage_coveragerc_check(toxenv_list, args):
    py = "py"
    cononical = "wandb/"
    cov_fname = args.coveragerc

    cf = configparser.ConfigParser()
    cf.read(cov_fname)

    paths = cf.get("paths", "canonicalsrc")
    paths = paths.split()

    toxenv_list = list(set(toxenv_list))
    toxenv_list.sort()

    # lets generate what paths should look like
    expected_paths = [cononical]
    for toxenv in toxenv_list:
        toxenv = toxenv.split(",")[0]
        _func, shard, py_ver = toxenv.split("-")

        assert py_ver.startswith(py)
        py_ver = py_ver[len(py) :]

        python = "".join(("python", py_ver[0], ".", py_ver[1:]))
        path = f".tox/{toxenv}/lib/{python}/site-packages/wandb/"
        expected_paths.append(path)

    if paths != expected_paths:
        print("Mismatch .coveragerc!")
        print("Seen:")
        for path in paths:
            print(f"    {path}")
        print("Expected:")
        for path in expected_paths:
            print(f"    {path}")
        sys.exit(1)


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


def main():
    parser, args = process_args()

    if args.action == "jobs":
        tasks = coverage_tasks(args)
        max_key_len = max(len(t) for t, _ in tasks)
        for k, v in tasks:
            print(f"{k:{max_key_len}} {v}")
    elif args.action == "check":
        tasks = coverage_tasks(args)
        # let's only count the main workflow
        main_tasks = list(filter(lambda x: x[0].split(".")[1] == "main", tasks))
        func_tasks = filter(lambda x: x[1].startswith("func-"), main_tasks)
        func_toxenvs = list(map(lambda x: x[1], func_tasks))
        coverage_config_check(len(main_tasks), args)
        coverage_coveragerc_check(func_toxenvs, args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
