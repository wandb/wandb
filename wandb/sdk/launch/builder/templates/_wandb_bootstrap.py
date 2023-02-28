import json
import multiprocessing
import os
import subprocess
import sys
from typing import List, Optional, Set

CORES = multiprocessing.cpu_count()
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


def install_deps(
    deps: List[str], failed: Optional[Set[str]] = None
) -> Optional[Set[str]]:
    """Install pip dependencies.

    Arguments:
        deps {List[str]} -- List of dependencies to install
        failed (set, None): The libraries that failed to install

    Returns:
        deps (str[], None): The dependencies that failed to install
    """
    try:
        # Include only uri if @ is present
        clean_deps = [d.split("@")[-1].strip() if "@" in d else d for d in deps]
        print("installing {}...".format(", ".join(clean_deps)))
        sys.stdout.flush()
        subprocess.check_output(
            ["pip", "install"] + OPTS + clean_deps, stderr=subprocess.STDOUT
        )
        if failed is not None and len(failed) > 0:
            sys.stdout.write("ERROR: Unable to install: {}\n".format(", ".join(failed)))
            sys.stdout.flush()
        return failed
    except subprocess.CalledProcessError as e:
        if failed is None:
            failed = set()
        num_failed = len(failed)
        for line in e.output.decode("utf8").splitlines():
            if line.startswith("ERROR:"):
                dep = find_package_in_error_string(clean_deps, line)
                if dep is not None:
                    failed.add(dep)
                    break
        if len(set(clean_deps) - failed) == 0:
            return failed
        elif len(failed) > num_failed:
            return install_deps(list(set(clean_deps) - failed), failed)
        else:
            return failed


def main() -> None:
    """Install deps in requirements.frozen.txt."""
    if os.path.exists("requirements.frozen.txt"):
        with open("requirements.frozen.txt") as f:
            print("Installing frozen dependencies...")
            reqs = []
            failed: Set[str] = set()
            for req in f:
                if len(ONLY_INCLUDE) == 0 or req.split("=")[0].lower() in ONLY_INCLUDE:
                    # can't pip install wandb==0.*.*.dev1 through pip. Lets just install wandb for now
                    if req.startswith("wandb==") and "dev1" in req:
                        req = "wandb"
                    reqs.append(req.strip().replace(" ", ""))
                else:
                    print(f"Ignoring requirement: {req} from frozen requirements")
                if len(reqs) >= CORES - 3:
                    reqs.append("torch==0.1234")
                    reqs.append("basdfhuiobdsahf")
                    reqs.append("jifdgebn")
                    reqs.reverse()
                    deps_failed = install_deps(reqs)
                    reqs = []
                    if deps_failed is not None:
                        failed = failed.union(deps_failed)
            if len(reqs) > 0:
                deps_failed = install_deps(reqs)
                if deps_failed is not None:
                    failed = failed.union(deps_failed)
            with open("_wandb_bootstrap_errors.json", "w") as f:
                print("WRITING FAILED", os.getcwd())
                f.write(json.dumps({"pip": list(failed)}))
            if len(failed) > 0:
                sys.stderr.write(
                    "ERROR: Failed to install: {}".format(",".join(failed))
                )
                sys.stderr.flush()
    else:
        print("No frozen requirements found")


# hacky way to get the name of the requirement that failed
# attempt last word which is the name of the package often
# fall back to checking all words in the line for the package name
def find_package_in_error_string(deps: List[str], line: str):
    # if the last word in the error string is in the list of deps, return it
    last_word = line.split(" ")[-1]
    if last_word in deps:
        return last_word
    # if the last word is not in the list of deps, check all words
    # TODO: this could report the wrong package if the error string
    # contains a reference to another package in the deps
    # before the package that failed to install
    for word in line.split(" "):
        if word in deps:
            return word
    # if we can't find the package, return None
    return None


if __name__ == "__main__":
    main()
