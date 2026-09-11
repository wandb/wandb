"""Run one SDK nox session in a temporary Kubernetes Job."""

# ruff: noqa: T201

import argparse
import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from pathlib import Path

WRAPPER = r"""
set -euo pipefail
mkdir -p /workspace/input/wheel /workspace/results
finish() {
  status=$?
  trap - EXIT
  printf '%s\n' "$status" > /workspace/results/exit-code
  touch /workspace/results/DONE
  echo "Tests finished with status $status; waiting for report collection."
  deadline=$((SECONDS + 180))
  until [[ -f /workspace/RELEASE ]] || (( SECONDS >= deadline )); do sleep 2; done
  exit "$status"
}
trap finish EXIT
deadline=$((SECONDS + 300))
until [[ -f /workspace/input/READY ]]; do
  if (( SECONDS >= deadline )); then echo "Input copy timed out." >&2; exit 124; fi
  sleep 2
done
status=0
timeout --signal=TERM --kill-after=15s "$TEST_TIMEOUT_SECONDS" \
  bash /workspace/input/run-tests.sh > >(tee /workspace/results/cluster.log) 2>&1 || status=$?
wait
exit "$status"
"""


class CancelledError(Exception):
    def __init__(self, signum):
        self.signum = signum


def cancel(signum, _frame):
    raise CancelledError(signum)


def manifest(args):
    run = re.sub(r"[^a-z0-9-]", "-", os.environ.get("GITHUB_RUN_ID", "local"))
    attempt = re.sub(r"[^a-z0-9-]", "-", os.environ.get("GITHUB_RUN_ATTEMPT", "1"))
    env = {
        "CI": "true",
        "SOURCE_COMMIT": args.commit,
        "NOX_SESSION": args.session,
        "PYTHON_VERSION": args.python,
        "WANDB_TEST_GROUP": args.test_group,
        "WANDB_TEST_GROUPS": args.test_groups,
        "WHEEL_SHA256": hashlib.sha256(args.wheel.read_bytes()).hexdigest(),
        "TEST_TIMEOUT_SECONDS": str(args.timeout_seconds),
    }
    if args.server_image:
        env["SERVER_IMAGE"] = args.server_image
    resources = {
        "requests": {"cpu": "2", "memory": "12Gi"},
        "limits": {"cpu": "8", "memory": "32Gi"},
    }
    pod = {
        "restartPolicy": "Never",
        "automountServiceAccountToken": False,
        "nodeSelector": {
            "cloud.google.com/gke-nodepool": args.nodepool,
            "kubernetes.io/arch": "amd64",
        },
        "containers": [
            {
                "name": "tests",
                "image": args.image,
                "imagePullPolicy": "IfNotPresent",
                "resources": resources,
                "env": [{"name": key, "value": value} for key, value in env.items()],
                "command": ["/bin/bash", "-c", WRAPPER],
                "volumeMounts": [{"name": "workspace", "mountPath": "/workspace"}],
            }
        ],
        "volumes": [{"name": "workspace", "emptyDir": {"sizeLimit": "30Gi"}}],
    }
    if args.server_image:
        pod["initContainers"] = [
            {
                "name": "server",
                "image": args.server_image,
                "imagePullPolicy": "IfNotPresent",
                "restartPolicy": "Always",
                "resources": resources,
                "env": [
                    {"name": "CI", "value": "1"},
                    {"name": "WANDB_ENABLE_TEST_CONTAINER", "value": "true"},
                ],
            }
        ]
    return {
        "apiVersion": "batch/v1",
        "kind": "Job",
        "metadata": {
            "generateName": f"wandb-sdk-{run}-{attempt}-"[:58],
            "namespace": args.namespace,
        },
        "spec": {
            "activeDeadlineSeconds": args.timeout_seconds + 600,
            "backoffLimit": 0,
            "ttlSecondsAfterFinished": 600,
            "template": {"spec": pod},
        },
    }


class ClusterTest:
    def __init__(self, args):
        self.args = args
        self.command = ["kubectl", "--namespace", args.namespace]
        self.job = None
        self.pod = None
        self.logs = None

    def kubectl(self, *args, timeout=45, check=True, **kwargs):
        result = subprocess.run(
            [*self.command, "--request-timeout=30s", *args],
            text=True,
            capture_output=True,
            timeout=timeout,
            **kwargs,
        )
        if check and result.returncode:
            raise RuntimeError(f"kubectl {' '.join(args[:3])}: {result.stderr.strip()}")
        return result

    def pod_state(self):
        pod = json.loads(self.kubectl("get", "pod", self.pod, "-o", "json").stdout)
        for container in pod.get("status", {}).get("containerStatuses", []):
            if container["name"] == "tests":
                return container["state"]
        return {}

    def exec(self, *args, **kwargs):
        return self.kubectl("exec", self.pod, "-c", "tests", "--", *args, **kwargs)

    def start(self):
        self.job = json.loads(
            self.kubectl(
                "create", "-f", "-", "-o", "json", input=json.dumps(manifest(self.args))
            ).stdout
        )["metadata"]
        print(
            f"Created Job {self.args.namespace}/{self.job['name']} ({self.job['uid']}).",
            flush=True,
        )
        deadline = time.monotonic() + 300
        while time.monotonic() < deadline:
            pods = json.loads(
                self.kubectl(
                    "get",
                    "pods",
                    "-l",
                    f"batch.kubernetes.io/controller-uid={self.job['uid']}",
                    "-o",
                    "json",
                ).stdout
            )["items"]
            for pod in pods:
                if any(
                    owner.get("uid") == self.job["uid"]
                    for owner in pod["metadata"].get("ownerReferences", [])
                ):
                    self.pod = pod["metadata"]["name"]
                    state = self.pod_state()
                    if "terminated" in state:
                        raise RuntimeError(
                            f"Test container stopped before receiving inputs: {state['terminated']}"
                        )
                    if "running" in state:
                        self.logs = subprocess.Popen(
                            [*self.command, "logs", "-f", self.pod, "-c", "tests"]
                        )
                        self.exec("mkdir", "-p", "/workspace/input/wheel")
                        self.kubectl(
                            "cp",
                            "-c",
                            "tests",
                            str(self.args.script),
                            f"{self.pod}:/workspace/input/run-tests.sh",
                            timeout=90,
                        )
                        self.kubectl(
                            "cp",
                            "-c",
                            "tests",
                            str(self.args.wheel),
                            f"{self.pod}:/workspace/input/wheel/{self.args.wheel.name}",
                            timeout=90,
                        )
                        self.exec("touch", "/workspace/input/READY")
                        return
            time.sleep(3)
        raise RuntimeError("Timed out waiting for the test container to start.")

    def wait(self):
        deadline = time.monotonic() + self.args.timeout_seconds + 30
        while time.monotonic() < deadline:
            result = self.exec(
                "sh",
                "-c",
                "test -f /workspace/results/DONE && cat /workspace/results/exit-code",
                check=False,
            )
            if result.returncode == 0:
                status = int(result.stdout.strip())
                if not 0 <= status <= 255:
                    raise RuntimeError(f"Invalid test exit status: {status}")
                return status
            state = self.pod_state()
            if "terminated" in state:
                print(
                    f"Test container stopped without a result: {state['terminated']}",
                    file=sys.stderr,
                )
                return state["terminated"]["exitCode"] or 1
            time.sleep(5)
        raise RuntimeError("Timed out waiting for the tests to finish.")

    def collect(self, timeout=90):
        with tempfile.TemporaryDirectory(prefix="wandb-cluster-results-") as directory:
            self.kubectl(
                "cp",
                "-c",
                "tests",
                f"{self.pod}:/workspace/results/.",
                directory,
                timeout=timeout,
            )
            reports = Path(directory)
            # Do not follow symlinks in reports copied out of the test container.
            for path in reports.rglob("*"):
                if path.is_symlink():
                    raise RuntimeError(
                        f"Unexpected symlink in test results: {path.relative_to(reports)}"
                    )
            for path in reports.rglob("*"):
                if path.is_file():
                    target = self.args.output / path.relative_to(reports)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(path, target)
            return all(
                (reports / name).is_file() and (reports / name).stat().st_size
                for name in (
                    "test-results/junit.xml",
                    "coverage.xml",
                    "source-commit.txt",
                )
            )

    def validate(self, status, reports_present):
        if status == 0:
            if not reports_present:
                raise RuntimeError(
                    "Successful tests did not produce JUnit, coverage, and source commit reports."
                )
            junit = ET.parse(self.args.output / "test-results/junit.xml")
            if not list(junit.iter("testcase")) or any(
                element.tag in ("failure", "error") for element in junit.iter()
            ):
                raise RuntimeError(
                    "Successful tests produced an empty or failing JUnit report."
                )
            ET.parse(self.args.output / "coverage.xml")
            if (
                self.args.output / "source-commit.txt"
            ).read_text().strip() != self.args.commit:
                raise RuntimeError("Tests ran against a different source commit.")

    def finish(self, status):
        self.exec("touch", "/workspace/RELEASE")
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            state = self.pod_state()
            if "terminated" in state:
                container_status = state["terminated"]["exitCode"]
                if container_status != status:
                    print(
                        f"Result status {status} differs from container status {container_status}.",
                        file=sys.stderr,
                    )
                return container_status or status
            time.sleep(2)
        raise RuntimeError("Test container did not stop after report collection.")

    def cleanup(self, cancelled=False):
        if self.logs:
            self.logs.terminate()
            try:
                self.logs.wait(timeout=1)
            except subprocess.TimeoutExpired:
                self.logs.kill()
                self.logs.wait(timeout=1)
        if self.pod and not cancelled:
            for container in ["tests", *(["server"] if self.args.server_image else [])]:
                try:
                    result = self.kubectl(
                        "logs", self.pod, "-c", container, timeout=10, check=False
                    )
                    target = (
                        self.args.output / "test-results" / f"cluster-{container}.log"
                    )
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text(result.stdout + result.stderr)
                except (OSError, subprocess.TimeoutExpired) as error:
                    print(
                        f"Could not collect {container} logs: {error}", file=sys.stderr
                    )
        if self.job and not cancelled:
            for kind, name in [("job", self.job["name"]), ("pod", self.pod)]:
                if name:
                    try:
                        result = self.kubectl(
                            "get", kind, name, "-o", "json", timeout=5
                        )
                        target = (
                            self.args.output / "test-results" / f"cluster-{kind}.json"
                        )
                        target.parent.mkdir(parents=True, exist_ok=True)
                        target.write_text(result.stdout)
                    except (OSError, RuntimeError, subprocess.TimeoutExpired) as error:
                        print(
                            f"Could not collect {kind} metadata: {error}",
                            file=sys.stderr,
                        )
        if self.job:
            # The API precondition prevents deleting a replacement with the same name.
            self.kubectl(
                "delete",
                "--raw",
                f"/apis/batch/v1/namespaces/{self.args.namespace}/jobs/{self.job['name']}",
                "-f",
                "-",
                input=json.dumps(
                    {
                        "apiVersion": "v1",
                        "kind": "DeleteOptions",
                        "propagationPolicy": "Foreground",
                        "preconditions": {"uid": self.job["uid"]},
                    }
                ),
                timeout=20,
            )
            print(f"Deleted Job {self.args.namespace}/{self.job['name']}.", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("commit", "image", "session", "python"):
        parser.add_argument(f"--{name}", required=True)
    parser.add_argument("--script", type=Path, required=True)
    parser.add_argument("--wheel", type=Path, required=True)
    parser.add_argument("--server-image", default="")
    parser.add_argument("--test-group", default="")
    parser.add_argument("--test-groups", default="")
    parser.add_argument(
        "--namespace", default=os.environ.get("KUBERNETES_NAMESPACE", "wandb-sdk-ci")
    )
    parser.add_argument("--nodepool", default="circle-generic")
    parser.add_argument("--output", type=Path, default=Path.cwd())
    parser.add_argument("--timeout-seconds", type=int, default=3000)
    args = parser.parse_args()
    if not re.fullmatch(r"[0-9a-f]{40}", args.commit):
        parser.error("--commit must be a full lowercase Git commit SHA")
    if not args.script.is_file() or not args.wheel.is_file():
        parser.error("--script and --wheel must be existing files")
    if args.timeout_seconds <= 0:
        parser.error("--timeout-seconds must be positive")
    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, cancel)
    run = ClusterTest(args)
    status = 1
    collected = False
    cancelled = False
    try:
        run.start()
        status = run.wait()
        reports_present = run.collect()
        collected = True
        status = run.finish(status)
        run.validate(status, reports_present)
    except CancelledError as error:
        cancelled = True
        status = 128 + error.signum
        print(f"Cancelled by signal {error.signum}.", file=sys.stderr)
    except (
        OSError,
        RuntimeError,
        ValueError,
        subprocess.TimeoutExpired,
        ET.ParseError,
    ) as error:
        status = status or 1
        print(f"Cluster tests failed: {error}", file=sys.stderr)
    finally:
        for signum in (signal.SIGINT, signal.SIGTERM):
            signal.signal(signum, signal.SIG_IGN)
        if run.pod and not collected and not cancelled:
            try:
                run.collect(timeout=15)
            except (OSError, RuntimeError, subprocess.TimeoutExpired) as error:
                print(f"Could not collect test results: {error}", file=sys.stderr)
        try:
            run.cleanup(cancelled=cancelled)
        except (OSError, RuntimeError, subprocess.TimeoutExpired) as error:
            status = status or 1
            print(f"Could not clean up the test Job: {error}", file=sys.stderr)
    return status


if __name__ == "__main__":
    sys.exit(main())
