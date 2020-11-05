#!/usr/bin/env python

import argparse
import configparser
import sys

import bumpversion


parser = argparse.ArgumentParser()
parser.add_argument("--to-dev", action="store_true", help="bump the dev version")
parser.add_argument("--from-dev", action="store_true", help="bump the dev version")
parser.add_argument("--debug", action="store_true", help="debug")
args = parser.parse_args()


def version_problem(current_version):
    print("Unhandled version string: {}".format(current_version))
    sys.exit(1)


def bump_release_to_dev(current_version):
    # Assume this is a released version
    parts = current_version.split(".")
    if len(parts) != 3:
        version_problem(current_version)
    major, minor, patch = parts

    patch_num = 0
    try:
        patch_num = int(patch)
    except ValueError:
        version_problem(current_version)

    new_version = "{}.{}.{}.dev1".format(major, minor, patch_num + 1)
    bump_args = []
    if args.debug:
        bump_args += ["--allow-dirty", "--dry-run", "--verbose"]
    bump_args += ["--new-version", new_version, "dev"]
    bumpversion.main(bump_args)


def bump_release_from_dev(current_version):
    # Assume this is a dev version
    parts = current_version.split(".")
    if len(parts) != 4:
        version_problem(current_version)
    major, minor, patch, _ = parts

    new_version = "{}.{}.{}".format(major, minor, patch)
    bump_args = []
    if args.debug:
        bump_args += ["--allow-dirty", "--dry-run", "--verbose"]
    bump_args += ["--new-version", new_version, "patch"]
    bumpversion.main(bump_args)


def main():
    config = configparser.ConfigParser()
    config.read("setup.cfg")
    current_version = config["bumpversion"]["current_version"]

    if args.to_dev:
        bump_release_to_dev(current_version)
    elif args.from_dev:
        bump_release_from_dev(current_version)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
