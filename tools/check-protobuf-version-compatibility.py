import pathlib
import platform
import re
import subprocess
import sys
from typing import List, Tuple

from pkg_resources import parse_version  # noqa: F401


def get_available_protobuf_versions() -> List[str]:
    """Get a list of available protobuf versions."""
    try:
        output = subprocess.check_output(
            ["pip", "index", "versions", "protobuf"],
        ).decode("utf-8")
        versions = list({o for o in output.split() if o[0].isnumeric()})
        versions = [v if not v.endswith(",") else v[:-1] for v in versions]
        return sorted(versions)
    except subprocess.CalledProcessError:
        return []


def parse_protobuf_requirements() -> List[Tuple[str, str]]:
    """Parse protobuf requirements from a requirements.txt file."""
    path_requirements = pathlib.Path(__file__).parent.parent / "requirements.txt"
    with open(path_requirements) as f:
        requirements = f.readlines()

    system_python_version = f"{sys.version_info.major}.{sys.version_info.minor}"
    system_platform = sys.platform
    system_machine = platform.machine()

    protobuf_reqs = []
    for line in requirements:
        if line.startswith("protobuf"):
            version_reqs = line.strip().split(";")[0]

            # first, check the system requirements
            system_reqs = line.strip().split(";")[1]
            # regex to find quoted python version in system_reqs
            python_version = re.search(
                r"python_version\s+([<>=!]+)\s+[',\"]([2,3]*[.][0-9]+)[',\"]",
                system_reqs,
            )
            if python_version is not None:
                version_check = (
                    f"parse_version({system_python_version!r}) "
                    f"{python_version.group(1)} "
                    f"parse_version({python_version.group(2)!r})"
                )
                if not eval(version_check):
                    continue
            # regex to find quoted platform in system_reqs
            platform_reqs = re.search(
                r"sys_platform\s+([<>=!]+)\s+[',\"]([a-z]+)[',\"]",
                system_reqs,
            )

            if platform_reqs is not None:
                if not eval(
                    f"{system_platform!r} {platform_reqs.group(1)} {platform_reqs.group(2)!r}"
                ):
                    continue

            # regex to find platform machine in system_reqs
            platform_machine = re.search(
                r"platform[.]machine\s+([<>=!]+)\s+[',\"]([a-z]+)[',\"]",
                system_reqs,
            )
            if platform_machine is not None:
                if not eval(
                    f"{system_machine!r} {platform_machine.group(1)} {platform_machine.group(2)!r}"
                ):
                    continue

            # finally, parse the protobuf version requirements
            reqs = version_reqs.split("protobuf")[1].split(",")
            print(reqs)
            for req in reqs:
                for i, char in enumerate(req):
                    if char.isnumeric():
                        protobuf_reqs.append(
                            (
                                req[:i].strip(),
                                req[i:].strip(),
                            )
                        )
                        break
    print(protobuf_reqs)
    return protobuf_reqs


def get_matching_versions(
    available_protobuf_vs: List[str], protobuf_reqs: List[Tuple[str, str]]
) -> List[str]:
    matching_vs = []
    for v in available_protobuf_vs:
        if all(
            eval(f"parse_version({v!r}) {rq[0]} parse_version({rq[1]!r})")
            for rq in protobuf_reqs
        ):
            matching_vs.append(v)

    return sorted(list(set(matching_vs)))


def attempt_install_protobuf_version(version: str) -> bool:
    try:
        subprocess.check_call(["pip", "install", f"protobuf=={version}"])
        subprocess.check_call(["python", "-c", "import wandb"])
        return True
    except subprocess.CalledProcessError:
        return False


if __name__ == "__main__":
    available_protobuf_versions = get_available_protobuf_versions()
    protobuf_requirements = parse_protobuf_requirements()
    matching_versions = get_matching_versions(
        available_protobuf_versions,
        protobuf_requirements,
    )

    version_compatibility = {
        version: attempt_install_protobuf_version(version)
        for version in matching_versions
    }

    for version, compatible in version_compatibility.items():
        print(f"protobuf=={version}: {compatible}")

    if not all(version_compatibility.values()):
        sys.exit(1)
