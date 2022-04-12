import json
import os
import subprocess
import sys

CORES = 1
ONLY_INCLUDE = {x for x in os.getenv("WANDB_ONLY_INCLUDE", "").split(",") if x != ""}
OPTS = []
# If the builder doesn't support buildx no need to use the cache
if os.getenv("WANDB_DISABLE_CACHE"):
    OPTS.append("--no-cache-dir")
# When installing all packages from requirements.frozen.txt no need to resolve deps
if len(ONLY_INCLUDE) == 0:
    OPTS.append("--no-deps")
# When installing the intersection of requirements.frozen.txt and requirements.txt
# force the frozen versions
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
        print("installing {}...".format(", ".join(deps)))
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
        for line in e.output.decode("utf8").split("\n"):
            if line.startswith("ERROR:"):
                failed.add(line.split(" ")[-1])
        failed = failed.intersection(deps)
        if len(failed) > num_failed:
            return install_deps(list(set(deps) - failed), failed)
        else:
            return failed


def main():
    """Install deps in requirements.frozen.txt"""
    if os.path.exists("requirements.frozen.txt"):
        with open("requirements.frozen.txt") as f:
            print("Installing frozen dependencies...")
            reqs = []
            failed = set()
            for req in f:
                if len(ONLY_INCLUDE) == 0 or req.split("=")[0].lower() in ONLY_INCLUDE:
                    # can't pip install wandb==0.*.*.dev1 through pip. Let's just install wandb for now
                    if req.startswith("wandb==") and "dev1" in req:
                        req = "wandb"
                    reqs.append(req.strip())
                else:
                    print(f"Ignoring requirement: {req} from frozen requirements")
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
            if len(failed) > 0:
                sys.stderr.write(
                    "ERROR: Failed to install: {}".format(",".join(failed))
                )
                sys.stderr.flush()
    else:
        print("No frozen requirements found")


if __name__ == "__main__":
    main()
