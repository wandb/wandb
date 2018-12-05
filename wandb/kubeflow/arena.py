import sh
import re
import os
import json
import time
import base64
import sys
import argparse
from distutils.spawn import find_executable
import shortuuid
from wandb.kubeflow import pipeline_metadata
from wandb.apis import InternalApi
from wandb import CommError


if not find_executable("arena"):
    if find_executable("docker"):
        arena = sh.Command(os.path.join(
            os.path.dirname(__file__), "./arena-docker.sh"))
    else:
        raise ValueError(
            "You must install arena or docker to run this command")
else:
    arena = sh.arena


def _short_id(length=8):
    uuid = shortuuid.ShortUUID(alphabet=list(
        "0123456789abcdefghijklmnopqrstuvwxyz"))
    return uuid.random(length)


class Arena(object):
    """A wrapper around arena that adds W&B config options"""

    def __init__(self, args, wandb_project=None, wandb_api_key=None,
                 wandb_run_id=None, timeout_minutes=10):
        self.api = InternalApi()
        self.args = args
        self.wandb_run_id = wandb_run_id or _short_id()
        self.wandb_project = wandb_project
        self.wandb_api_key = wandb_api_key or self.api.api_key
        self.timeout_minutes = timeout_minutes
        self.workers = int(self._parse_flag("--workers", 1)[1] or "0")
        self.entity = None

    def _parse_flag(self, flag, default=-1):
        index = next((i for i, arg in enumerate(self.args)
                      if re.match(r"{}[= ]".format(flag), arg)), default)
        if index > -1 and len(self.args) > index:
            if "=" in self.args[index]:
                val = self.args[index].split("=", 1)[1]
            elif " " in self.args[index]:
                val = self.args[index].split(" ", 1)[1]
            else:
                val = True
        else:
            val = None
        return index, val

    def submit(self):
        try:
            from minio import Minio
            from google.cloud import storage
        except ImportError:
            raise ValueError(
                "Required libraries for kubeflow aren't installed, run `pip install wandb[kubeflow]`")

        print('Submitting arena {} job 🚀'.format(
            self.args[0]))

        # TODO: require command?
        opt_index, _ = self._parse_flag("--", len(self.args) - 1)
        name_index, name = self._parse_flag("--name")
        if name_index == -1:
            name = "wandb"
            name_index = len(self.args) - 1
            self.args.insert(name_index, None)
        name = '-'.join([name, _short_id(5)])
        self.args[name_index] = "--name="+name

        projo = self.wandb_project or self.api.settings("project")
        if projo:
            if "/" in projo:
                ent, projo = projo.split("/")
                self.args.insert(
                    opt_index, "--env=WANDB_ENTITY={}".format(ent))
        else:
            _, git = self._parse_flag("--syncSource")
            _, image = self._parse_flag("--image")
            if git:
                projo = git.split("/")[-1].replace(".git", "")
            elif image:
                projo = image.split(":")[0]
            if projo:
                projo = self.api.format_project(projo)
                self.args.insert(
                    opt_index, "--env=WANDB_PROJECT={}".format(projo))

        if self.wandb_api_key:
            self.args.insert(
                opt_index, "--env=WANDB_API_KEY={}".format(self.wandb_api_key))
        else:
            # Extract the secret, ideally this would be a secret env in the TFjob YAML
            try:
                kube_args = {"o": "json"}
                index, namespace = self._parse_flag("--namespace")
                if namespace:
                    kube_args["namespace"] = namespace
                secret = json.loads(str(sh.kubectl(
                    "get", "secret", "wandb", **kube_args)))
            except sh.ErrorReturnCode:
                secret = {}
            if secret.get("data"):
                print("Found wandb k8s secret, adding to environment")
                api_key = secret["data"].get("api_key")
                if api_key:
                    self.args.insert(
                        opt_index, "--env=WANDB_API_KEY="+base64.b64decode(api_key).decode("utf8"))
                    self.wandb_api_key = api_key
        if self.wandb_api_key:
            try:
                # TODO: support someone overriding entity
                if self.workers <= 1:
                    res = self.api.upsert_run(
                        name=self.wandb_run_id, project=projo)
                    wandb_run_path = os.path.join(
                        res["project"]["entity"]["name"], res["project"]["name"], "runs", res["name"])
                    print('Run configured with W&B\nview live results here: {}'.format(
                        "https://app.wandb.ai/"+wandb_run_path))
                    self.args.insert(
                        opt_index, "--env=WANDB_RUN_ID={}".format(res["name"]))
                    self.args.insert(
                        opt_index, "--env=WANDB_RESUME=allow")
                else:
                    res = self.api.viewer()
                    self.args.insert(
                        opt_index, "--env=WANDB_RUN_GROUP="+name
                    )
                    wandb_run_path = os.path.join(
                        res["entity"], projo, "groups", name)
                    print('Distributed run configured with W&B\nview live results here: {}'.format(
                        "https://app.wandb.ai/"+wandb_run_path))
            except CommError:
                print("Failed to talk to W&B")
        else:
            print(
                "Couldn't authenticate with W&B, run `wandb login` on your local machine")
        index, gcs_url = self._parse_flag("--logdir")
        tensorboard = self._parse_flag("--tensorboard")[0] > -1
        if gcs_url and wandb_run_path:
            pipeline_metadata(gcs_url, wandb_run_path, tensorboard)
        elif wandb_run_path:
            print("--logdir isn't set, skipping pipeline asset saving.")
        cmd = arena(["submit"] + self.args)
        print("Arena job {} submitted, watching state for upto {} minutes".format(
            name, self.timeout_minutes))
        total_time = 0
        poll_rate = 10
        while True:
            # TODO: parse JSON when it's supported
            status = str(arena("get", name)).split("\n")
            rows = [row for row in (re.split(r"\s+", row)
                                    for row in status) if len(row) == 6 and "s" in row[3]]
            if len(rows) <= 1:
                print("Final status: ", rows)
                break
            status = [row[1] for row in rows[1:]]
            runtime = [row[3] for row in rows[1:]]
            print("Status: {} {}".format(status, runtime))
            if not all([s in ("PENDING", "RUNNING") for s in status]):
                if not any([s in ("PENDING", "RUNNING") for s in status]):
                    print("Job finished with statuses: {}".format(status))
                    if any([s == "FAILED" for s in status]):
                        arena("logs", name, _fg=True)
                    break
            time.sleep(poll_rate)
            total_time += 10
            if total_time > 90:
                poll_rate = 30
            if total_time > self.timeout_minutes * 60:
                print("Timeout exceeded")


def main():
    parser = argparse.ArgumentParser("arena", add_help=False)
    parser.add_argument('-h', '--help', action='store_true', dest='help')
    parser.add_argument("--wandb-project", type=str, default=None)
    parser.add_argument("--wandb-api-key", type=str, default=None)
    parser.add_argument("--wandb-run-id", type=str, default=None)
    parser.add_argument("--wandb-install", action="store_true")
    parser.add_argument("--timeout-minutes", type=int, default=10)
    known, unknown = parser.parse_known_args()
    if known.help:
        return arena(unknown + ["--help"], _fg=True)

    subcommand = None
    if len(unknown) > 0:
        subcommand = unknown[0]
    wandb_arena = Arena(unknown, wandb_project=known.wandb_project, wandb_api_key=known.wandb_api_key,
                        wandb_run_id=known.wandb_run_id, timeout_minutes=known.timeout_minutes)
    if subcommand == "submit":
        wandb_arena.args.pop(0)
        wandb_arena.submit()
    else:
        arena(unknown, _fg=True)


if __name__ == "__main__":
    main()
