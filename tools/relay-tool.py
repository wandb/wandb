#!/usr/bin/env python

import logging
import os
import subprocess
import netrc
import wandb

import pathlib
import sys
import argparse

import flask.cli

flask.cli.show_server_banner = lambda *args: None

root_path = pathlib.Path(__file__).resolve().parent.parent
conftest_path = root_path / "tests" / "unit_tests"
sys.path.insert(0, os.fspath(conftest_path))
from conftest import RelayServer


def startup_relay(base_url):
    inject = []
    log = logging.getLogger("werkzeug")
    log.setLevel(logging.ERROR)
    _relay_server = RelayServer(base_url=base_url, inject=inject, relay_link=True)
    _relay_server.start()
    return _relay_server.relay_url


def run(my_env, command):
    proc = subprocess.Popen(command, env=my_env)
    res = proc.wait()
    print("result", res)


def shell(my_env, command):
    # Not supported yet, need to do some fork fun and stdout funkiness
    cmd = ["zsh"]
    cmd += command
    os.execve("/bin/zsh", cmd, my_env)
    # shouldnt get here
    print("DONE")


def main():
    parser = argparse.ArgumentParser(
        description="W&B Relay wrapper", allow_abbrev=False
    )
    # parser.add_argument("--shell", action="store_true")
    parser.add_argument("--base_url", default="api.wandb.ai")
    parser.add_argument("commmand", nargs=argparse.REMAINDER)
    args = parser.parse_args()

    net = netrc.netrc()
    got = net.authenticators(args.base_url)
    user, account, passwd = got

    if len(args.commmand) == 0:
        print("Expected command to run.")
        parser.print_help()
        sys.exit(1)

    relay_url = startup_relay("https://" + args.base_url)

    my_env = {
        "WANDB_BASE_URL": relay_url,
        "WANDB_API_KEY": passwd,
        "WANDB_CONSOLE": "off",
        "RELAY_LINK": relay_url,
    }
    env = os.environ.copy()
    env.update(my_env)

    run(env, command=args.commmand)


if __name__ == "__main__":
    main()
