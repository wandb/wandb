import atexit
import logging
import os
import signal
import subprocess
import sys
import time

from flask import Flask, jsonify, request  # TODO: decide if we want this dependency...
import requests
import wandb
from wandb.apis import PublicApi
from wandb.compat import tempfile


tempdir = os.getenv("WANDB_TEMPDIR")
if tempdir is None:
    tempdir = tempfile.TemporaryDirectory("wandb-service-server").name
logdir = os.path.join(tempdir, "logs")
wandb.util.mkdir_exists_ok(logdir)


class Service(object):
    def __init__(self, cmd, env=None, max_instances=5):
        self._cmd = cmd
        self._env = env or {}
        self.max_instances = max_instances
        self.cmd = []
        self.opts = {}
        self.env = {}
        self.api = PublicApi()

    def bind(self, opts=None):
        self.opts.update(opts or {})
        self.cmd = self._cmd.copy()
        self.env = self._env.copy()
        for opt, val in opts.items():
            self.cmd = [
                c.replace("${}".format(opt.upper()), str(val)) for c in self.cmd
            ]
            for k, v in self.env.items():
                self.env[k] = v.replace("${}".format(opt.upper()), str(val))
        # TODO: make this optional?
        self.env.update(os.environ)

    def opt(self, key, opts=None):
        opts = opts or {}
        return self.opts.get(key, opts.get(key))

    def setup(self, opts=None):
        pass


class TensorboardService(Service):
    def setup(self, opts=None):
        # TODO: put me in a thread
        path = self.opt("path", opts)
        logdir = self.opt("logdir", opts)
        if path is not None and not os.path.exists(logdir):
            wandb.util.mkdir_exists_ok(logdir)
            run = self.api.run(path)
            for file in run.files():
                if "tfevents" in file.name:
                    file.download(logdir)


class JupyterLabService(Service):
    def setup(self, opts=None):
        tempdir = self.opt("tempdir", opts)
        port = self.opt("port", opts)
        host = self.opt("host", opts)
        # path = self.opt("path", opts)
        # TODO: namespace
        with open(os.path.join(tempdir, "jupyter_notebook_config.py"), "w") as f:
            f.write(
                """
c.NotebookApp.token = ''
c.NotebookApp.password = ''
c.NotebookApp.open_browser = False
c.NotebookApp.port = %s
c.NotebookApp.base_url = '/services/proxies/%s/%s/'
c.NotebookApp.allow_origin = 'https://local.wandb.test'
c.NotebookApp.tornado_settings = {
    'headers': {
        'Content-Security-Policy': "frame-ancestors https://local.wandb.test 'self' "
    }
}"""
                % (port, host, port)
            )


class ProcessManager(object):
    """ProcessManager starts processes on the current host and provides a control
    plane"""

    DIR = tempdir
    SERVICES = {
        "tensorboard": TensorboardService(
            ["tensorboard", "--logdir", "$LOGDIR", "--port", "$PORT"]
        ),
        "jupyterlab": JupyterLabService(
            ["jupyter", "lab", "--config", "$TEMPDIR/jupyter_notebook_config.py"]
        ),
        "server": Service(
            [sys.executable, "-u", os.path.abspath(__file__)],
            env={"PORT": "$PORT", "WANDB_TEMPDIR": "$TEMPDIR"},
        ),
        "inlets": Service(
            [
                "inlets",
                "client",
                "--strict-forwarding=false",
                "--remote",
                "$URL/services/proxies/$HOST",
                "--upstream",
                "http://127.0.0.1:$PORT",
                "--token",
                "$APIKEY",
            ]
        ),
    }
    PROCS = []

    def __init__(self, service_name, opts=None):
        opts = opts or {}
        self.port = opts.get("port", wandb.util.free_port())
        self.opts = {"port": self.port}
        self.opts.update(opts)
        self.service_name = service_name
        self.service = self.SERVICES.get(service_name)
        self.service.bind(self.opts)
        self._popen = None
        if self.service is None:
            raise AttributeError(
                "Unsupported service: {}, supported services: {}".format(
                    service_name, self.SERVICES.keys()
                )
            )

    def verify(self):
        verified = False
        if self.status == "running":
            for _ in range(5):
                try:
                    res = requests.get("http://127.0.0.1:{}".format(self.port))
                    res.raise_for_status()
                    verified = True
                except requests.RequestException:
                    time.sleep(1)
        return verified

    def launch(self, opts=None):
        existing_proc = None
        running = []
        for proc in self.PROCS:
            if proc.service_name == self.service_name:
                if proc.status == "running":
                    running.append(proc)
                    if self.key and proc.key == self.key:
                        existing_proc = proc
        if len(running) >= self.service.max_instances:
            print(
                "Found {} running {} instances, terminating pid {}".format(
                    len(running), self.service_name, running[0].pid
                )
            )
            running[0].terminate()
        if existing_proc:
            print("Using existing process", existing_proc.pid)
            self.port = existing_proc.port
            self._popen = existing_proc._popen
            return self.verify()
        self.service.setup(opts)
        self._popen = subprocess.Popen(
            self.service.cmd,
            env=self.service.env,
            stderr=subprocess.STDOUT,
            stdout=open(os.path.join(logdir, "{}.log".format(self.service_name)), "a"),
        )
        self.PROCS.append(self)
        return self.verify()

    @property
    def key(self):
        return self.opts.get("key")

    @property
    def pid(self):
        if self._popen:
            return self._popen.pid

    @property
    def status(self):
        status = "pending"
        if self._popen is not None:
            if self._popen.poll() is not None:
                status = "exited"
            else:
                status = "running"
        return status

    def _signal(self, sig, timeout=3):
        if self.pid is None:
            return False
        try:
            os.kill(self.pid, sig)
        except ProcessLookupError:
            return True  # process is gone
        stopped = False
        for _ in range(3):
            if self._popen.poll() is not None:
                stopped = True
                self.PROCS.remove(self)
                break
            time.sleep(1)
        return stopped

    def terminate(self):
        stopped = self._signal(signal.SIGTERM)
        if not stopped:
            return self._signal(signal.SIGKILL)


def create_app():
    app = Flask(__name__)
    tensorboarddir = os.path.join(tempdir, "tensorboard")
    wandb.util.mkdir_exists_ok(tensorboarddir)

    def launch_service(proc, service, body):
        app.logger.info("Launching {} for run: {}".format(service, body["path"]))
        launched = proc.launch(body)
        if not launched:
            app.logger.error("Failed to launch tensorboard")
        else:
            app.logger.info(
                "{} running at: {} (pid {})".format(service, proc.port, proc.pid)
            )
        return jsonify({"port": str(proc.port)})

    @app.route("/")
    def index():
        return jsonify({"message": "W&B Launch server {}".format(wandb.__version__)})

    @app.route("/api/launch", methods=["POST"])
    def launch():
        body = request.get_json()
        app.logger.info("Received: {}".format(body))
        if body["service"] == "tensorboard":
            logdir = os.path.join(tensorboarddir, *body["path"].split("/"))
            proc = ProcessManager(
                "tensorboard", {"key": body["path"], "logdir": logdir}
            )
            return launch_service(proc, "tensorboard", body)
        elif body["service"] == "jupyterlab":
            proc = ProcessManager("jupyterlab", {"key": "jupyter", "tempdir": tempdir})
            return launch_service(proc, "jupyterlab", body)
        app.logger.warn("Unknown service requested {}".format(body["service"]))
        return jsonify({"error": "Un-supported service {}".format(body["service"])})

    @app.route("/api/status", methods=["GET"])
    def status():
        status = {"services": []}
        for proc in ProcessManager.PROCS:
            status["services"].append(
                {"port": proc.port, "pid": proc.pid, "status": proc.status}
            )
        return jsonify(status)

    @app.errorhandler(404)
    def page_not_found(e):
        return jsonify({"error": "Page not found"}), 404

    @app.errorhandler(500)
    def internal_error(e):
        return jsonify({"error": "Server error: {}".format(e)})

    return app


def process_cleanup(*args, **kwargs):
    for proc in ProcessManager.PROCS:
        proc.terminate()


atexit.register(process_cleanup)

if __name__ == "__main__":
    app = create_app()
    app.logger.setLevel(logging.INFO)
    app.run(debug=False, port=int(os.environ.get("PORT", wandb.util.free_port())))
