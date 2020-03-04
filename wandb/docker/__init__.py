import os
import requests
import six
import logging
from wandb.docker import auth
from wandb.docker import www_authenticate
import subprocess
entrypoint = os.path.join(os.path.dirname(
    os.path.abspath(__file__)), "wandb-entrypoint.sh")
auth_config = auth.load_config()
log = logging.getLogger(__name__)


def shell(cmd):
    "Simple wrapper for calling docker, returning None on error and the output on success"
    try:
        return subprocess.check_output(['docker'] + cmd, stderr=subprocess.STDOUT).decode('utf8').strip()
    except subprocess.CalledProcessError:
        return None


def default_image(gpu=False):
    tag = "all"
    if not gpu:
        tag += "-cpu"
    return "wandb/deepo:%s" % tag


def parse_repository_tag(repo_name):
    parts = repo_name.rsplit('@', 1)
    if len(parts) == 2:
        return tuple(parts)
    parts = repo_name.rsplit(':', 1)
    if len(parts) == 2 and '/' not in parts[1]:
        return tuple(parts)
    return repo_name, None


def parse(image_name):
    repository, tag = parse_repository_tag(image_name)
    registry, repo_name = auth.resolve_repository_name(repository)
    if registry == "docker.io":
        registry = "index.docker.io"
    return registry, repo_name, tag or "latest"


def auth_token(registry, repo):
    """Makes a request to the root of a v2 docker registry to get the auth url.

    Always returns a dictionary, if there's no token key we couldn't authenticate
    """
    # TODO: Cache tokens?
    auth_info = auth_config.resolve_authconfig(registry)
    if auth_info:
        normalized = {k.lower(): v for k, v in six.iteritems(auth_info)}
        auth_info = (normalized.get("username"), normalized.get("password"))
    response = requests.get("https://{}/v2/".format(registry), timeout=3)
    if response.headers.get("www-authenticate"):
        try:
            info = www_authenticate.parse(response.headers['www-authenticate'])
        except ValueError:
            info = {}
    else:
        log.error("Received {} when attempting to authenticate with {}".format(
            response, registry))
        info = {}
    if info.get("bearer"):
        res = requests.get(info["bearer"]["realm"] +
                           "?service={}&scope=repository:{}:pull".format(
            info["bearer"]["service"], repo), auth=auth_info, timeout=3)
        res.raise_for_status()
        return res.json()
    return {}


def image_id_from_registry(image_name):
    """Get the docker id from a public or private registry"""
    registry, repository, tag = parse(image_name)
    res = None
    try:
        token = auth_token(registry, repository).get("token")
        # dockerhub is crazy
        if registry == "index.docker.io":
            registry = "registry-1.docker.io"
        res = requests.head("https://{}/v2/{}/manifests/{}".format(registry, repository, tag), headers={
            "Authorization": "Bearer {}".format(token),
            "Accept": "application/vnd.docker.distribution.manifest.v2+json"
        }, timeout=5)
        res.raise_for_status()
    except requests.RequestException:
        log.error("Received {} when attempting to get digest for {}".format(
            res, image_name))
        return None
    return "@".join([registry+"/"+repository, res.headers["Docker-Content-Digest"]])


def image_id(image_name):
    """Retreve the image id from the local docker daemon or remote registry"""
    if "@sha256:" in image_name:
        return image_name
    else:
        return shell(['inspect', image_name, '--format', '{{index .RepoDigests 0}}']) or image_id_from_registry(image_name)
