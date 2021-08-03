import multiprocessing
import os
import json
import subprocess
import sys

CORES = multiprocessing.cpu_count()
ONLY_INCLUDE = set(os.getenv("WANDB_ONLY_INCLUDE", "").split(","))
OPTS = []
if os.getenv("WANDB_DISABLE_CACHE"):
    OPTS.append("--no-cache-dir")
if len(ONLY_INCLUDE) == 0:
    OPTS.append("--no-deps")
else:
    OPTS.append("--force")


def install_deps(deps, failed=None):
    """Install pip dependencies

    Arguments:
        failed (set, None): The libraries that failed to install

    Returns:
        deps (str[], None): The dependencies that failed to install
    """
    try:
        print("{}...".format(", ".join(deps)))
        sys.stdout.flush()
        subprocess.check_output(
            ["pip", "install"] + OPTS + deps, stderr=subprocess.STDOUT
        )
        if failed is not None and len(failed) > 0:
            sys.stderr.write("ERROR: Unable to install: {}".format(", ".join(deps)))
            sys.stderr.flush()
        return failed
    except subprocess.CalledProcessError as e:
        if failed is None:
            failed = set()
        num_failed = len(failed)
        for line in e.output.decode("utf8"):
            if line.startswith("ERROR:"):
                failed.add(line.split(" ")[-1])
        if len(failed) > num_failed:
            return install_deps(list(set(deps) - failed), failed)
        else:
            return failed


def main():
    """Install deps in requirements.frozen.txt"""
    print("Installing frozen dependencies...")
    with open("requirements.frozen.txt") as f:
        reqs = []
        failed = set()
        for req in f:
            if len(ONLY_INCLUDE) == 0 or req.split("=")[0].lower() in ONLY_INCLUDE:
                reqs.append(req.strip())
            if len(reqs) >= CORES:
                deps_failed = install_deps(reqs)
                reqs = []
                if deps_failed is not None:
                    failed = failed.union(deps_failed)
        if len(reqs) > 0:
            deps_failed = install_deps(reqs)
            if deps_failed is not None:
                failed = failed.union(deps_failed)
        with open("_wandb_bootstrap_errors.json", "w") as f:
            f.write(json.dumps({"pip": list(failed)}))
        sys.stderr.write("ERROR: Failed to install: {}".format(",".join(failed)))
        sys.stderr.flush()


if __name__ == "__main__":
    main()
