import os

import boto3
import botocore
from utils import run_cmd


def pytest_addoption(parser):
    parser.addoption("--api-key", action="store", default=None)
    parser.addoption("--base-url", action="store", default=None)


def pytest_generate_tests(metafunc):
    """Fixture to make api_key and base_url available in tests."""
    api_key = metafunc.config.option.api_key
    if "api_key" in metafunc.fixturenames:
        metafunc.parametrize("api_key", [api_key])
    base_url = metafunc.config.option.base_url
    if "base_url" in metafunc.fixturenames:
        metafunc.parametrize("base_url", [base_url])


def pytest_configure(config):
    """Fixture to confirm the session has the correct credentials."""
    client_config = botocore.config.Config(region_name="us-east-2")
    sts = boto3.client("sts", config=client_config)
    try:
        sts.get_caller_identity()
    except botocore.exceptions.ClientError:
        raise Exception("Not logged into LaunchSandbox AWS account")

    creds_path = os.path.expanduser("~/.aws")
    run_cmd(
        "kubectl delete secret generic aws-secret --ignore-not-found -n wandb-release-testing"
    )
    run_cmd(
        f"kubectl create secret generic aws-secret --from-file={creds_path} -n wandb-release-testing"
    )
