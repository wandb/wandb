from __future__ import annotations

import importlib.util
import os
import urllib.error
import urllib.request
from typing import Any

METADATA_URL = "http://169.254.169.254/opc/v2"


def collect(metadata_url: str = METADATA_URL, sdk: Any = None) -> dict[str, str]:
    """Read this instance's pool through an installed OCI SDK and credential path."""
    result = {"collector": "oci_instance_pool"}
    if sdk is None and importlib.util.find_spec("oci") is None:
        return {**result, "status": "unavailable", "reason": "missing_dependency"}
    principal = os.environ.get("OCI_CLI_AUTH") == "instance_principal"
    config_file = os.path.expanduser(
        os.environ.get("OCI_CLI_CONFIG_FILE")
        or os.environ.get("OCI_CONFIG_FILE")
        or "~/.oci/config"
    )
    if not principal and not os.path.isfile(config_file):
        return {**result, "status": "unavailable", "reason": "missing_credentials"}
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        request = urllib.request.Request(
            metadata_url + "/instance/instancePoolId",
            headers={"Authorization": "Bearer Oracle"},
        )
        pool = opener.open(request, timeout=0.5).read(512).decode().strip()
    except urllib.error.HTTPError:
        return {**result, "status": "unavailable", "reason": "not_in_instance_pool"}
    except (OSError, ValueError):
        return {**result, "status": "unavailable", "reason": "metadata_unavailable"}
    if sdk is None:
        import oci as sdk
    try:
        if principal:
            kwargs = {
                "signer": sdk.auth.signers.InstancePrincipalsSecurityTokenSigner()
            }
            config = {}
        else:
            kwargs, config = {}, sdk.config.from_file(file_location=config_file)
        client = sdk.core.ComputeManagementClient(
            config,
            timeout=(1, 2),
            retry_strategy=sdk.retry.NoneRetryStrategy(),
            **kwargs,
        )
        client.get_instance_pool(pool)
    except Exception as error:
        status = getattr(error, "status", None)
        if status in (401, 403, 404):
            return {
                **result,
                "status": "permission_denied",
                "reason": "permission_denied",
            }
        if "timeout" in type(error).__name__.lower():
            return {**result, "status": "timeout", "reason": "request_timeout"}
        return {**result, "status": "unavailable", "reason": "request_failed"}
    return {
        **result,
        "status": "available",
        "source": "get_instance_pool",
        "topology_value": pool,
    }
