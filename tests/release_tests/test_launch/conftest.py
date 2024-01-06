import os
from netrc import netrc

import boto3
import botocore
from utils import run_cmd


def pytest_addoption(parser):
    parser.addoption("--api-key", action="store", default=None)
    parser.addoption("--base-url", action="store", default=None)
    parser.addoption("--agent-image", action="store", default=None)


def pytest_generate_tests(metafunc):
    """Fixture to make options available in tests."""
    api_key = metafunc.config.option.api_key
    if "api_key" in metafunc.fixturenames:
        metafunc.parametrize("api_key", [api_key])
    base_url = metafunc.config.option.base_url
    if "base_url" in metafunc.fixturenames:
        metafunc.parametrize("base_url", [base_url])
    agent_image = metafunc.config.option.agent_image
    if "agent_image" in metafunc.fixturenames:
        metafunc.parametrize("agent_image", [agent_image])


def pytest_configure(config):
    """Fixture to confirm the session has the correct credentials."""
    client_config = botocore.config.Config(region_name="us-east-2")
    sts = boto3.client("sts", config=client_config)
    try:
        sts.get_caller_identity()
    except botocore.exceptions.ClientError:
        raise Exception("Not logged into LaunchSandbox AWS account")

    default_image = "wandb-launch-agent:release-testing"
    agent_image = config.option.agent_image
    if not agent_image:
        run_cmd(f"python tools/build_launch_agent.py --tag {default_image}")

    default_base_url = "api.wandb.ai"
    if not config.option.base_url:
        config.option.base_url = default_base_url

    if not config.option.api_key:
        n = netrc()
        # returns tuple in format (login, account, key)
        config.option.api_key = n.authenticators(config.option.base_url)[2]

    creds_path = os.path.expanduser("~/.aws")
    run_cmd(
        "kubectl delete secret generic aws-secret --ignore-not-found -n wandb-release-testing"
    )
    run_cmd(
        f"kubectl create secret generic aws-secret --from-file={creds_path} -n wandb-release-testing"
    )
