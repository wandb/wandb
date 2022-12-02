#!/usr/bin/env python
"""
  wandb_mitm run python ./train.py
  wandb_mitm --port 123 pause --service graphql
  wandb_mitm --port 123 watch
"""

import logging
import os
import subprocess
import netrc
import wandb
import urllib

import pathlib
import sys
import argparse

import flask.cli


def startup_relay(base_url):
    from relay import RelayServer

    flask.cli.show_server_banner = lambda *args: None
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
    parser.add_argument("--base_url", default="https://api.wandb.ai")
    parser.add_argument("--relay_link")
    parser.add_argument("--pause")
    parser.add_argument("--unpause")
    parser.add_argument("--limit")
    parser.add_argument("--unlimit")
    parser.add_argument("--time")
    parser.add_argument("--requests")
    parser.add_argument("--watch", action="store_true")
    parser.add_argument("--trace", action="store_true")
    parser.add_argument("commmand", nargs=argparse.REMAINDER)
    args = parser.parse_args()

    netloc = urllib.parse.urlparse(args.base_url).netloc
    net = netrc.netrc()
    got = net.authenticators(netloc)
    user, account, passwd = got

    if not args.relay_link and len(args.commmand) == 0:
        print("Expected command to run.")
        parser.print_help()
        sys.exit(1)

    relay_url = startup_relay(args.base_url)

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
