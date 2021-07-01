#!/usr/bin/env python

import time
import ast
import argparse
import glob
import subprocess
import sys
import shutil
import yaml
import os
import requests


def load_docstring(filepath):
    file_contents = ""
    with open(filepath) as fd:
        file_contents = fd.read()
    module = ast.parse(file_contents)
    docstring = ast.get_docstring(module)
    if docstring is None:
        docstring = ""
    return docstring


# From: github.com/marshmallow-code/apispec
def load_yaml_from_docstring(docstring):
    """Loads YAML from docstring."""
    split_lines = docstring.split("\n")

    # Cut YAML from rest of docstring
    for index, line in enumerate(split_lines):
        line = line.strip()
        if line.startswith("---"):
            cut_from = index
            break
    else:
        return None

    yaml_string = "\n".join(split_lines[cut_from:])
    return yaml.load(yaml_string, Loader=yaml.BaseLoader)


def wandb_dir_safe_cleanup(base_dir=None):
    """make sure directory has only wandb like files before deleting."""

    prefix = "wandb/"
    fnames = glob.glob("{}*".format(prefix))
    if not fnames:
        return
    filtered = []
    allowed = {"latest-run", "debug-internal.log", "debug.log"}
    for f in fnames:
        # print("CHECK:", f)
        assert f.startswith(prefix)
        f = f[len(prefix) :]
        if f in allowed:
            continue
        if f.startswith("run-"):
            continue
        print("UNEXPECTED:", f)
        sys.exit(1)

    print("INFO: removing cleanish wandb dir")
    shutil.rmtree(prefix)


class Test:
    def __init__(self, tname, args):
        self._tname = tname
        self._args = args
        self._retcode = None

    def _run(self):
        tname = self._tname
        print("RUN:", tname)
        cmd = "./{}".format(tname)
        # cmd_list = [cmd]
        if self._args.base:
            base = "{}/wandb/".format(self._args.base)
            cmd_list = [
                "coverage",
                "run",
                "--branch",
                "--source",
                base,
                "--parallel-mode",
                cmd,
            ]
        else:
            cmd_list = ["coverage", "run", "--branch", "--parallel-mode", cmd]
        print("RUNNING", cmd_list)
        p = subprocess.Popen(cmd_list)
        try:
            p.communicate(timeout=120)
        except subprocess.TimeoutExpired:
            print("TIMEOUT")
            p.kill()
            try:
                p.communicate(timeout=30)
            except subprocess.TimeoutExpired:
                print("ERROR: double timeout")
                sys.exit(1)
        print("DONE:", p.returncode)
        self._retcode = p.returncode
        # https://stackoverflow.com/questions/18344932/python-subprocess-call-stdout-to-file-stderr-to-file-display-stderr-on-scree
        # https://stackoverflow.com/questions/2715847/read-streaming-input-from-subprocess-communicate
        # ret = subprocess.call(cmd)
        # p = subprocess.Popen([cmd], stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        # t = subprocess.Popen(['tee', 'log_file'], stdin=p.stdout)
        # p.stdout.close()
        # t.communicate()

    def _prep(self):
        """Cleanup and/or populate wandb dir."""
        wandb_dir_safe_cleanup()
        # load file and docstring eval criteria

        docstr = load_docstring(self._tname)
        spec = load_yaml_from_docstring(docstr)
        print("SPEC:", spec)

    def _fin(self):
        """Reap anything in wandb dir"""
        pass

    def run(self):
        self._prep()
        self._run()
        self._fin()


class TestRunner:
    def __init__(self, args):
        self._args = args
        self._test_files = []
        self._results = {}

    def _populate(self):
        for x in glob.glob("t_[0-9-]*_*.py"):
            self._test_files.append(x)
        self._test_files.sort()

    def _runall(self):
        for tname in self._test_files:
            if self._args.dryrun:
                print("DRYRUN:", tname)
                continue
            t = Test(tname, args=self._args)
            t.run()
            self._capture_result(t)
            break

    def _capture_result(self, t):
        self._results[t._tname] = t._retcode

    def run(self):
        self._populate()
        self._runall()

    def finish(self):
        for k in sorted(self._results):
            print("{}: {}".format(k, self._results[k]))


import socket


class Backend:
    def __init__(self):
        pass

    def _free_port(self):
        sock = socket.socket()
        sock.bind(("", 0))
        _, port = sock.getsockname()
        return port

    def start(self):
        port = self._free_port()
        root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../"))
        path = os.path.join(root, "tests", "utils", "mock_server.py")
        command = [sys.executable, "-u", path]
        env = os.environ
        env["PORT"] = str(port)
        env["PYTHONPATH"] = root
        worker_id = 1
        logfname = os.path.join(
            root,
            "tests",
            "logs",
            "standalone-live_mock_server-{}.log".format(worker_id),
        )
        logfile = open(logfname, "w")
        server = subprocess.Popen(
            command,
            stdout=logfile,
            env=env,
            stderr=subprocess.STDOUT,
            bufsize=1,
            close_fds=True,
        )
        server._port = port
        server.base_url = "http://localhost:%i" % server._port
        self._server = server
        started = False
        for i in range(10):
            try:
                res = requests.get("%s/ctx" % server.base_url, timeout=5)
                if res.status_code == 200:
                    started = True
                    break
                print("Attempting to connect but got: %s" % res)
            except requests.exceptions.RequestException:
                print(
                    "Timed out waiting for server to start...",
                    server.base_url,
                    time.time(),
                )
                if server.poll() is None:
                    time.sleep(1)
                else:
                    raise ValueError("Server failed to start.")
        if started:
            print("Mock server listing on {} see {}".format(server._port, logfname))
        else:
            server.terminate()
            print("Server failed to launch, see {}".format(logfname))
            raise Exception("problem")

        os.environ["WANDB_BASE_URL"] = "http://127.0.0.1:{}".format(port)
        os.environ["WANDB_API_KEY"] = "1824812581259009ca9981580f8f8a9012409eee"

    def stop(self):
        if self._server:
            self._server.terminate()
            self._server = None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dryrun", action="store_true")
    parser.add_argument("--base", default="")
    args = parser.parse_args()

    backend = Backend()
    try:
        backend.start()
        tr = TestRunner(args)
        tr.run()
        tr.finish()
    finally:
        backend.stop()


if __name__ == "__main__":
    main()
