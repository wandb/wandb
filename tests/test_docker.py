import pytest
from .utils import git_repo
import os
import glob
import sys
from wandb import docker


@pytest.fixture
def auth_config(mocker):
    mocker.patch('wandb.docker.auth_config.resolve_authconfig',
                 lambda reg: {"Username": "test", "Password": "test"})


@pytest.fixture
def auth_config_funky(mocker):
    mocker.patch('wandb.docker.auth_config.resolve_authconfig',
                 lambda reg: {"username": "test"})


def test_docker_registry_custom(request_mocker, auth_config):
    auth_mock = request_mocker.register_uri('GET', "https://gcr.io/v2/", headers={"Www-Authenticate": 'Bearer realm="https://gcr.io/token",service="gcr.io",scope="repository:foo/bar:pull"'},
                                            content=b'{}', status_code=401)
    token_mock = request_mocker.register_uri(
        'GET', "https://gcr.io/token", content=b'{"token": "test"}')
    mani_mock = request_mocker.register_uri(
        'HEAD', "https://gcr.io/v2/foo/bar/manifests/rad", headers={"Docker-Content-Digest": "sha256:sickdigest"})
    digest = docker.image_id_from_registry("gcr.io/foo/bar:rad")
    assert digest == "gcr.io/foo/bar@sha256:sickdigest"


def test_registry_fucked(request_mocker, auth_config):
    auth_mock = request_mocker.register_uri(
        'GET', "https://crap.io/v2/", content=b'{}', status_code=404)
    mani_mock = request_mocker.register_uri(
        'HEAD', "https://crap.io/v2/foo/bar/manifests/rad", status_code=404)
    digest = docker.image_id_from_registry("crap.io/foo/bar:rad")
    assert digest == None


def test_docker_registry_hub(request_mocker, auth_config_funky):
    request_mocker.register_uri('GET', "https://index.docker.io/v2/", headers={"Www-Authenticate": 'Bearer realm="https://auth.docker.io/token",service="registry.docker.io",scope="repository:samalba/my-app:pull,push'},
                                content=b'{}', status_code=401)
    token_mock = request_mocker.register_uri(
        'GET', "https://auth.docker.io/token", content=b'{"token": "test"}')
    mani_mock = request_mocker.register_uri(
        'HEAD', "https://registry-1.docker.io/v2/foo/bar/manifests/rad", headers={"Docker-Content-Digest": "sha256:sickdigest"})
    docker.image_id_from_registry("foo/bar:rad")
