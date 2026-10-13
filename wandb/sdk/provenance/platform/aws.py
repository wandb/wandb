from __future__ import annotations

import importlib.util
import urllib.request
from typing import Any

METADATA_URL = "http://169.254.169.254"


def collect(metadata_url: str = METADATA_URL, session: Any = None) -> dict[str, str]:
    """Report this instance's nearest network node via DescribeInstanceTopology."""
    result = {"collector": "aws_instance_topology"}
    if session is None and importlib.util.find_spec("botocore") is None:
        return {**result, "status": "unavailable", "reason": "missing_dependency"}
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        token = opener.open(
            urllib.request.Request(
                metadata_url + "/latest/api/token",
                method="PUT",
                headers={"X-aws-ec2-metadata-token-ttl-seconds": "60"},
            ),
            timeout=0.5,
        ).read(4096)
        identity = {}
        for field in ("instance-id", "placement/region"):
            request = urllib.request.Request(
                metadata_url + "/latest/meta-data/" + field,
                headers={"X-aws-ec2-metadata-token": token.decode().strip()},
            )
            identity[field] = opener.open(request, timeout=0.5).read(256).decode()
    except (OSError, ValueError):
        return {**result, "status": "unavailable", "reason": "metadata_unavailable"}
    import botocore.config
    import botocore.exceptions
    import botocore.session

    if session is None:
        session = botocore.session.get_session()
        session.set_config_variable("metadata_service_timeout", 1)
        session.set_config_variable("metadata_service_num_attempts", 1)
    try:
        if session.get_credentials() is None:
            return {**result, "status": "unavailable", "reason": "missing_credentials"}
        client = session.create_client(
            "ec2",
            region_name=identity["placement/region"].strip(),
            config=botocore.config.Config(
                connect_timeout=1, read_timeout=2, retries={"max_attempts": 1}
            ),
        )
        response = client.describe_instance_topology(
            InstanceIds=[identity["instance-id"].strip()]
        )
    except botocore.exceptions.ClientError as error:
        code = error.response.get("Error", {}).get("Code", "")
        if code in ("UnauthorizedOperation", "AccessDenied", "AccessDeniedException"):
            return {
                **result,
                "status": "permission_denied",
                "reason": "permission_denied",
            }
        return {**result, "status": "unavailable", "reason": "request_failed"}
    except (
        botocore.exceptions.ConnectTimeoutError,
        botocore.exceptions.ReadTimeoutError,
    ):
        return {**result, "status": "timeout", "reason": "request_timeout"}
    except botocore.exceptions.BotoCoreError:
        return {**result, "status": "unavailable", "reason": "request_failed"}
    instances = response.get("Instances") or [{}]
    nodes = instances[0].get("NetworkNodes") or []
    if not nodes or not isinstance(nodes[-1], str):
        return {**result, "status": "partial", "reason": "topology_not_reported"}
    return {
        **result,
        "status": "available",
        "source": "describe_instance_topology",
        "topology_value": nodes[-1],
    }
