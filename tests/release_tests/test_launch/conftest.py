import os
from netrc import netrc

import boto3
import botocore
import pytest
from utils import run_cmd


def pytest_addoption(parser):
    parser.addoption("--api-key", action="store", default=None)
    parser.addoption("--base-url", action="store", default=None)
    parser.addoption("--agent-image", action="store", default=None)


@pytest.fixture(scope="session", autouse=True)
def ensure_credentials(pytestconfig):
    """Fixture to confirm the session has the correct credentials."""
    client_config = botocore.config.Config(region_name="us-east-2")
    sts = boto3.client("sts", config=client_config)
    try:
        sts.get_caller_identity()
    except botocore.exceptions.ClientError:
        raise Exception("Not logged into LaunchSandbox AWS account")

    default_image = "wandb-launch-agent:release-testing"
    agent_image = pytestconfig.option.agent_image
    if not agent_image:
        run_cmd(f"python tools/build_launch_agent.py --tag {default_image}")

    creds_path = os.path.expanduser("~/.aws")
    run_cmd(
        "kubectl delete secret generic aws-secret --ignore-not-found -n wandb-release-testing"
    )
    run_cmd(
        f"kubectl create secret generic aws-secret --from-file={creds_path} -n wandb-release-testing"
    )


@pytest.fixture(scope="session")
def api_key(pytestconfig) -> str:
    api_key = pytestconfig.option.api_key

    if not api_key:
        n = netrc()
        netrc_tuple = n.authenticators(pytestconfig.option.base_url)
        assert netrc_tuple  # (login, account, key)
        api_key = netrc_tuple[2]

    return api_key


@pytest.fixture()
def base_url(pytestconfig) -> str:
    return pytestconfig.option.base_url or "api.wandb.ai"


@pytest.fixture()
def agent_image(pytestconfig) -> str:
    return pytestconfig.option.agent_image
