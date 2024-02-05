"""This file exists to share common elements between...

- `system_tests/conftest.py`; and
- `system_tests/test_importers/test_wandb/conftest.py`

because pytest doesn't like it when you import from a conftest.py directly.
"""


import dataclasses
import subprocess
import time
import urllib.parse
from typing import Optional

import requests

# `local-testcontainer` ports
LOCAL_BASE_PORT = "8080"
SERVICES_API_PORT = "8083"
FIXTURE_SERVICE_PORT = "9015"

DEFAULT_SERVER_CONTAINER_NAME = "wandb-local-testcontainer"
DEFAULT_SERVER_VOLUME = "wandb-local-testcontainer-vol"


@dataclasses.dataclass
class WandbServerSettings:
    name: str
    volume: str
    wandb_server_pull: str
    wandb_server_image_registry: str
    wandb_server_image_repository: str
    wandb_server_tag: str
    # spin up the server or connect to an existing one
    wandb_server_use_existing: bool
    # ports exposed to the host
    local_base_port: str
    services_api_port: str
    fixture_service_port: str
    # ports internal to the container
    internal_local_base_port: str = LOCAL_BASE_PORT
    internal_local_services_api_port: str = SERVICES_API_PORT
    internal_fixture_service_port: str = FIXTURE_SERVICE_PORT
    url: str = "http://localhost"

    base_url: Optional[str] = None

    def __post_init__(self):
        self.base_url = f"{self.url}:{self.local_base_port}"


def spin_wandb_server(settings: WandbServerSettings) -> bool:
    base_url = settings.base_url
    app_health_endpoint = "healthz"
    fixture_url = base_url.replace(
        settings.local_base_port, settings.fixture_service_port
    )
    fixture_health_endpoint = "health"

    if settings.wandb_server_use_existing:
        return check_server_health(base_url=base_url, endpoint=app_health_endpoint)

    if not check_server_health(base_url, app_health_endpoint):
        command = [
            "docker",
            "run",
            "--pull",
            settings.wandb_server_pull,
            "--rm",
            "-v",
            f"{settings.volume}:/vol",
            "-p",
            f"{settings.local_base_port}:{settings.internal_local_base_port}",
            "-p",
            f"{settings.services_api_port}:{settings.internal_local_services_api_port}",
            "-p",
            f"{settings.fixture_service_port}:{settings.internal_fixture_service_port}",
            "-e",
            "WANDB_ENABLE_TEST_CONTAINER=true",
            "--name",
            settings.name,
            "--platform",
            "linux/amd64",
            f"{settings.wandb_server_image_registry}/{settings.wandb_server_image_repository}:{settings.wandb_server_tag}",
        ]
        subprocess.Popen(command)
        # wait for the server to start
        server_is_up = check_server_health(
            base_url=base_url, endpoint=app_health_endpoint, num_retries=30
        )
        if not server_is_up:
            return False
        # check that the fixture service is accessible
        return check_server_health(
            base_url=fixture_url,
            endpoint=fixture_health_endpoint,
            num_retries=30,
        )

    return check_server_health(
        base_url=fixture_url, endpoint=fixture_health_endpoint, num_retries=10
    )


def check_server_health(
    base_url: str, endpoint: str, num_retries: int = 1, sleep_time: int = 1
) -> bool:
    """Check if wandb server is healthy.

    :param base_url:
    :param num_retries:
    :param sleep_time:
    :return:
    """
    for _ in range(num_retries):
        try:
            response = requests.get(urllib.parse.urljoin(base_url, endpoint))
            if response.status_code == 200:
                return True
            time.sleep(sleep_time)
        except requests.exceptions.ConnectionError:
            time.sleep(sleep_time)
    return False
