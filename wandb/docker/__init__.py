import logging
import os
import subprocess
from typing import Any, Dict, List, Optional, Tuple, Union

from dockerpycreds.utils import find_executable  # type: ignore
import requests
from wandb.docker import auth
from wandb.docker import www_authenticate
from wandb.errors import DockerError


entrypoint = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "wandb-entrypoint.sh"
)
auth_config = auth.load_config()
log = logging.getLogger(__name__)


def shell(cmd: List[str]) -> Optional[str]:
    """Simple wrapper for calling docker,

    returning None on error and the output on success"""
    try:
        return (
            subprocess.check_output(["docker"] + cmd, stderr=subprocess.STDOUT)
            .decode("utf8")
            .strip()
        )
    except subprocess.CalledProcessError as e:
        print(e)
        return None


_buildx_installed = None


def is_buildx_installed() -> bool:
    """Returns `True` if docker buildx is installed and working."""
    global _buildx_installed
    if _buildx_installed is not None:
        return _buildx_installed
    if not find_executable("docker"):
        _buildx_installed = False
    else:
        help_output = shell(["buildx", "--help"])
        _buildx_installed = help_output is not None and "buildx" in help_output
    return _buildx_installed


def build(tags: List[str], file: str, context_path: str) -> str:
    command = ["buildx", "build"] if is_buildx_installed() else ["build"]
    build_tags = []
    for tag in tags:
        build_tags += ["-t", tag]
    run(
        ["docker"] + command + build_tags + ["-f", file, context_path],
        capture_stderr=False,
        capture_stdout=False,
    )
    return tags[0]


def run(
    args: List[Any],
    capture_stdout: bool = True,
    capture_stderr: bool = True,
    input: bytes = None,
    return_stderr: bool = False,
    env: Optional[Dict[str, str]] = None,
) -> Union[str, Tuple[str, str]]:
    args = [str(x) for x in args]
    subprocess_env = dict(os.environ)
    subprocess_env.update(env or {})
    if args[1] == "buildx":
        subprocess_env["DOCKER_CLI_EXPERIMENTAL"] = "enabled"
    if capture_stdout:
        stdout_dest = subprocess.PIPE
    else:
        stdout_dest = None
    if capture_stderr:
        stderr_dest = subprocess.PIPE
    else:
        stderr_dest = None

    completed_process = subprocess.run(
        args, input=input, stdout=stdout_dest, stderr=stderr_dest, env=subprocess_env
    )
    if completed_process.returncode != 0:
        raise DockerError(
            args,
            completed_process.returncode,
            completed_process.stdout,
            completed_process.stderr,
        )

    if return_stderr:
        return (
            _post_process_stream(completed_process.stdout),
            _post_process_stream(completed_process.stderr),
        )
    else:
        return _post_process_stream(completed_process.stdout)


def _post_process_stream(stream: Optional[bytes]) -> str:
    if stream is None:
        return ""
    stream = stream.decode()
    if len(stream) != 0 and stream[-1] == "\n":
        stream = stream[:-1]
    return stream


def default_image(gpu=False) -> str:
    tag = "all"
    if not gpu:
        tag += "-cpu"
    return "wandb/deepo:%s" % tag


def parse_repository_tag(repo_name: str) -> Tuple[Optional[str]]:
    parts = repo_name.rsplit("@", 1)
    if len(parts) == 2:
        return tuple(parts)
    parts = repo_name.rsplit(":", 1)
    if len(parts) == 2 and "/" not in parts[1]:
        return tuple(parts)
    return repo_name, None


def parse(image_name: str) -> Tuple[str]:
    repository, tag = parse_repository_tag(image_name)
    registry, repo_name = auth.resolve_repository_name(repository)
    if registry == "docker.io":
        registry = "index.docker.io"
    return registry, repo_name, tag or "latest"


def auth_token(registry: str, repo: str) -> Dict[str, str]:
    """Makes a request to the root of a v2 docker registry to get the auth url.

    Always returns a dictionary, if there's no token key we couldn't authenticate
    """
    # TODO: Cache tokens?
    auth_info = auth_config.resolve_authconfig(registry)
    if auth_info:
        normalized = {k.lower(): v for k, v in auth_info.items()}
        auth_info = (normalized.get("username"), normalized.get("password"))
    response = requests.get(f"https://{registry}/v2/", timeout=3)
    if response.headers.get("www-authenticate"):
        try:
            info = www_authenticate.parse(response.headers["www-authenticate"])
        except ValueError:
            info = {}
    else:
        log.error(
            "Received {} when attempting to authenticate with {}".format(
                response, registry
            )
        )
        info = {}
    if info.get("bearer"):
        res = requests.get(
            info["bearer"]["realm"]
            + "?service={}&scope=repository:{}:pull".format(
                info["bearer"]["service"], repo
            ),
            auth=auth_info,
            timeout=3,
        )
        res.raise_for_status()
        return res.json()
    return {}


def image_id_from_registry(image_name: str) -> Optional[str]:
    """Get the docker id from a public or private registry"""
    registry, repository, tag = parse(image_name)
    res = None
    try:
        token = auth_token(registry, repository).get("token")
        # dockerhub is crazy
        if registry == "index.docker.io":
            registry = "registry-1.docker.io"
        res = requests.head(
            f"https://{registry}/v2/{repository}/manifests/{tag}",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.docker.distribution.manifest.v2+json",
            },
            timeout=5,
        )
        res.raise_for_status()
    except requests.RequestException:
        log.error(f"Received {res} when attempting to get digest for {image_name}")
        return None
    return "@".join([registry + "/" + repository, res.headers["Docker-Content-Digest"]])


def image_id(image_name: str) -> Optional[str]:
    """Retreve the image id from the local docker daemon or remote registry"""
    if "@sha256:" in image_name:
        return image_name
    else:
        return shell(
            ["inspect", image_name, "--format", "{{index .RepoDigests 0}}"]
        ) or image_id_from_registry(image_name)


def get_image_uid(image_name: str) -> int:
    """Retreve the image default uid through brute force"""
    return int(shell(["run", image_name, "id", "-u"]))


def push(image: str, tag: str) -> Optional[str]:
    """Push an image to a remote registry"""
    return shell(["push", f"{image}:{tag}"])


def login(username: str, password: str, registry: str) -> Optional[str]:
    """Login to a registry"""
    return shell(["login", "--username", username, "--password", password, registry])


def tag(image_name: str, tag: str) -> Optional[str]:
    """Tag an image"""
    return shell(["tag", image_name, tag])


__all__ = [
    "shell",
    "build",
    "run",
    "image_id",
    "image_id_from_registry",
    "auth_token",
    "parse",
    "parse_repository_tag",
    "default_image",
    "get_image_uid",
    "push",
    "login",
    "tag",
]
