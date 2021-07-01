#!/usr/bin/env python

import time
import argparse
import glob
import subprocess
import socket
import sys
import shutil
import yaml
import os
import requests

# Allow this script to load wandb and tests modules
client_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../"))
sys.path.insert(1, client_dir)

from tests.utils.mock_server import ParseCTX
from tests.standalone.testlib import testspec, testcfg


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
        self._test_cfg = None

    def _run(self):
        tname = self._tname
        print("RUN:", tname)
        cmd = "./{}".format(tname)
        # cmd_list = [cmd]
        cmd_list = ["coverage", "run", cmd]
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

    def _prep(self):
        """Cleanup and/or populate wandb dir."""
        wandb_dir_safe_cleanup()
        # load file and docstring eval criteria

        docstr = testspec.load_docstring(self._tname)
        spec = testspec.load_yaml_from_docstring(docstr)
        print("SPEC:", spec)
        cfg = testcfg.TestlibConfig(spec)
        print("TESTCFG", cfg)
        self._test_cfg = cfg

    def _fin(self):
        """Reap anything in wandb dir"""
        pass

    def run(self):
        self._prep()
        if not self._args.dryrun:
            self._run()
        self._fin()


class TestRunner:
    def __init__(self, args, backend):
        self._args = args
        self._backend = backend
        self._test_files = []
        self._results = {}

    def _populate(self):
        for x in glob.glob("t_[0-9-]*_*.py"):
            self._test_files.append(x)
        self._test_files.sort()

    def _runall(self):
        for tname in self._test_files:
            t = Test(tname, args=self._args)
            self._backend.reset()
            t.run()
            self._capture_result(t)
            break

    def _capture_result(self, t):
        test_cfg = t._test_cfg
        if not test_cfg:
            return
        ctx = self._backend.get_state()
        got = ParseCTX(ctx)
        print("DEBUG config", got.config)
        print("DEBUG summary", got.summary)
        runs = test_cfg.get("run")
        if runs is not None:
            # only support one run right now
            assert len(runs) == 1
            run = runs[0]
            config = run.get("config")
            exit = run.get("exit")
            summary = run.get("summary")
            print("CHECK", exit, config, summary)

        self._results[t._tname] = t._retcode

    def run(self):
        self._populate()
        self._runall()

    def finish(self):
        for k in sorted(self._results):
            print("{}: {}".format(k, self._results[k]))


class Backend:
    def __init__(self, args):
        self._args = args
        self._server = None

    def _free_port(self):
        sock = socket.socket()
        sock.bind(("", 0))
        _, port = sock.getsockname()
        return port

    def start(self):
        if self._args.dryrun:
            return
        if self._args.live:
            return
        # TODO: consolidate with github.com/wandb/client:tests/conftest.py
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

        def get_ctx():
            return requests.get(server.base_url + "/ctx").json()

        def set_ctx(payload):
            return requests.put(server.base_url + "/ctx", json=payload).json()

        def reset_ctx():
            return requests.delete(server.base_url + "/ctx").json()

        server.get_ctx = get_ctx
        server.set_ctx = set_ctx
        server.reset_ctx = reset_ctx

        server._port = port
        server.base_url = "http://localhost:%i" % server._port
        self._server = server
        started = False
        for i in range(30):
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
        DUMMY_API_KEY = "1824812581259009ca9981580f8f8a9012409eee"
        os.environ["WANDB_API_KEY"] = DUMMY_API_KEY

    def reset(self):
        if not self._server:
            return
        self._server.reset_ctx()

    def get_state(self):
        if not self._server:
            return
        ret = self._server.get_ctx()
        return ret

    def stop(self):
        if not self._server:
            return
        self._server.terminate()
        self._server = None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dryrun", action="store_true")
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()

    backend = Backend(args=args)
    try:
        backend.start()
        tr = TestRunner(args=args, backend=backend)
        tr.run()
        tr.finish()
    finally:
        backend.stop()


if __name__ == "__main__":
    main()
