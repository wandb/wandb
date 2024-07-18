import json
import os
import re
import subprocess
import sys
from typing import List, Optional, Set

FAILED_PACKAGES_PREFIX = "ERROR: Failed to install: "
FAILED_PACKAGES_POSTFIX = ". During automated build process."
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

TORCH_DEP_REGEX = r"torch(vision|audio)?==\d+\.\d+\.\d+(\+(?:cu[\d]{2,3})|(?:\+cpu))?"


def install_deps(
    deps: List[str],
    failed: Optional[Set[str]] = None,
    extra_index: Optional[str] = None,
    opts: Optional[List[str]] = None,
) -> Optional[Set[str]]:
    """Install pip dependencies.

    Arguments:
        deps {List[str]} -- List of dependencies to install
        failed (set, None): The libraries that failed to install

    Returns:
        deps (str[], None): The dependencies that failed to install
    """
    try:
        subprocess.check_output(["pip", "install", "uv"], stderr=subprocess.STDOUT)
        # Include only uri if @ is present
        clean_deps = [d.split("@")[-1].strip() if "@" in d else d for d in deps]
        index_args = ["--extra-index-url", extra_index] if extra_index else []
        print("installing {}...".format(", ".join(clean_deps)))
        opts = opts or []
        args = ["uv", "pip", "install"] + opts + clean_deps + index_args
        sys.stdout.flush()
        subprocess.check_output(args, stderr=subprocess.STDOUT)
        return failed
    except subprocess.CalledProcessError as e:
        if failed is None:
            failed = set()
        num_failed = len(failed)
        current_pkg = None
        for line in e.output.decode("utf8").splitlines():
            # Since the name of the package might not be on the same line as
            # the error msg, keep track of the currently installing package
            current_pkg = get_current_package(line, clean_deps, current_pkg)

            if "error: subprocess-exited-with-error" in line:
                if current_pkg is not None:
                    failed.add(current_pkg)
            elif line.startswith("ERROR:"):
                clean_dep = find_package_in_error_string(clean_deps, line)
                if clean_dep is not None:
                    if clean_dep in deps:
                        failed.add(clean_dep)
                    else:
                        for d in deps:
                            if clean_dep in d:
                                failed.add(d.replace(" ", ""))
                                break
        if len(set(clean_deps) - failed) == 0:
            return failed
        elif len(failed) > num_failed:
            return install_deps(
                list(set(clean_deps) - failed),
                failed,
                extra_index=extra_index,
                opts=opts,
            )
        else:
            return failed


def main() -> None:
    """Install deps in requirements.frozen.txt."""
    extra_index = None
    torch_reqs = []
    if os.path.exists("requirements.frozen.txt"):
        with open("requirements.frozen.txt") as f:
            print("Installing frozen dependencies...")
            reqs = []
            for req in f:
                if (
                    len(ONLY_INCLUDE) == 0
                    or req in ONLY_INCLUDE
                    or req.split("=")[0].lower() in ONLY_INCLUDE
                ):
                    # can't pip install wandb==0.*.*.dev1 through pip. Lets just install wandb for now
                    if req.startswith("wandb==") and "dev1" in req:
                        req = "wandb"
                    match = re.match(
                        TORCH_DEP_REGEX,
                        req,
                    )
                    if match:
                        variant = match.group(2)
                        if variant:
                            extra_index = (
                                f"https://download.pytorch.org/whl/{variant[1:]}"
                            )
                        torch_reqs.append(req.strip().replace(" ", ""))
                    else:
                        reqs.append(req.strip().replace(" ", ""))
                else:
                    print(f"Ignoring requirement: {req} from frozen requirements")
            failed = install_deps(reqs, opts=OPTS) or set()
            with open("_wandb_bootstrap_errors.json", "w") as f:
                f.write(json.dumps({"pip": list(failed)}))
            if len(failed) > 0:
                sys.stderr.write(
                    FAILED_PACKAGES_PREFIX + ",".join(failed) + FAILED_PACKAGES_POSTFIX
                )
                sys.stderr.flush()
        install_deps(torch_reqs, extra_index=extra_index)
    else:
        print("No frozen requirements found")


def add_version_to_package_name(deps: List[str], package: str) -> Optional[str]:
    """Add the associated version to a package name.

    For example: `my-package` -> `my-package==1.0.0`
    """
    for dep in deps:
        if dep.split("==")[0] == package:
            return dep
    return None


def get_current_package(
    line: str, deps: List[str], current_pkg: Optional[str]
) -> Optional[str]:
    """Tries to pull a package name from the line.

    Used to keep track of what the currently-installing package is,
    in case an error message isn't on the same line as the package
    """
    # "Collecting my-package==1.0.0"
    if line.startswith("Collecting"):
        return line.split(" ")[1]
    # "Building wheel for my-package (pyproject.toml): finished with status 'error'"
    elif line.strip().startswith("Building wheel") and line.strip().endswith(
        "finished with status 'error'"
    ):
        return add_version_to_package_name(deps, line.strip().split(" ")[3])
    # "Running setup.py install for my-package: finished with status 'error'"
    elif line.strip().startswith("Running setup.py install") and line.strip().endswith(
        "finished with status 'error'"
    ):
        return add_version_to_package_name(deps, line.strip().split(" ")[4][:-1])
    return current_pkg


# hacky way to get the name of the requirement that failed
# attempt last word which is the name of the package often
# fall back to checking all words in the line for the package name
def find_package_in_error_string(deps: List[str], line: str) -> Optional[str]:
    # if the last word in the error string is in the list of deps, return it
    last_word = line.split(" ")[-1]
    if last_word in deps:
        return last_word
    # if the last word is not in the list of deps, check all words
    # TODO: this could report the wrong package if the error string
    # contains a reference to another package in the deps
    # before the package that failed to install
    for word in line.split(" "):
        if word.strip(",") in deps:
            return word
    # if we can't find the package, return None
    return None


if __name__ == "__main__":
    main()
