import pytest
import wandb
from wandb.sdk.artifacts.storage_handlers.s3_handler import S3Handler

COREWEAVE_ENDPOINT_TEST_CASES = [
    # Direct matches from the predefined list
    ("https://cwobject.com", True),
    ("https://cwobject.com/", True),
    ("http://cwlota.com", True),
    ("accel-object.lga1.coreweave.com", True),
    ("https://object.lga1.coreweave.com/", True),
    ("cwobject.com", True),  # No scheme, https should be added
    ("https://accel-object.lga1.coreweave.com", True),
    # Case-insensitive: hostnames + schemes must match regardless of case.
    ("HTTPS://CWOBJECT.COM", True),
    ("HTTPS://OBJECT.LGA1.COREWEAVE.COM", True),
    ("HTTP://CWLOTA.COM", True),
    ("cwlota.com", False),  # This will default to https://cwlota.com
    ("http://object.lga1.coreweave.com", False),  # invalid http scheme
    ("https://s3.amazonaws.com", False),
    ("https://coreweave.com", False),
    ("https://object.coreweave.com.malicious.com", False),
    ("", False),
    ("https://object.lga1..coreweave.com", False),
]


@pytest.mark.parametrize(
    "endpoint_url, expected",
    COREWEAVE_ENDPOINT_TEST_CASES,
)
def test_is_coreweave_endpoint(endpoint_url, expected):
    """Tests the S3Handler._is_coreweave_endpoint method with various URLs."""
    handler = S3Handler()
    assert handler._is_coreweave_endpoint(endpoint_url) == expected


BACKBLAZE_ENDPOINT_TEST_CASES = [
    # Canonical path-style S3 endpoints (one per region shape).
    ("https://s3.us-west-004.backblazeb2.com", True),
    ("https://s3.us-west-004.backblazeb2.com/", True),
    ("https://s3.eu-central-003.backblazeb2.com", True),
    ("s3.us-west-004.backblazeb2.com", True),  # missing scheme defaults to https
    # Virtual-hosted-style: "<bucket>.s3.<region>.backblazeb2.com".
    ("https://my-bucket.s3.us-west-004.backblazeb2.com", True),
    ("https://my.dotted.bucket.s3.us-west-004.backblazeb2.com", True),
    # Case-insensitive: hostnames + schemes must match regardless of case.
    ("HTTPS://S3.US-WEST-004.BACKBLAZEB2.COM", True),
    ("HTTPS://MY-BUCKET.S3.US-WEST-004.BACKBLAZEB2.COM", True),
    # Negatives: native b2 API, AWS, lookalikes, empty.
    ("https://api.backblazeb2.com", False),
    ("https://f004.backblazeb2.com", False),
    ("https://backblazeb2.com", False),
    ("https://s3.amazonaws.com", False),
    ("https://s3.us-west-004.backblazeb2.com.malicious.com", False),
    ("https://cwobject.com", False),
    ("", False),
]


@pytest.mark.parametrize(
    "endpoint_url, expected",
    BACKBLAZE_ENDPOINT_TEST_CASES,
)
def test_is_backblaze_endpoint(endpoint_url, expected):
    """Tests the S3Handler._is_backblaze_endpoint method with various URLs."""
    handler = S3Handler()
    assert handler._is_backblaze_endpoint(endpoint_url) == expected


# One representative URL per registered S3-compatible provider, plus a few
# unrecognized ones. The dispatcher should return the provider name (or None).
S3_COMPATIBLE_PROVIDER_TEST_CASES = [
    ("https://cwobject.com", "coreweave"),
    ("https://object.lga1.coreweave.com/", "coreweave"),
    ("http://cwlota.com", "coreweave"),
    ("https://s3.us-west-004.backblazeb2.com", "backblaze"),
    ("https://my-bucket.s3.us-west-004.backblazeb2.com", "backblaze"),
    ("https://s3.amazonaws.com", None),
    ("https://example.com", None),
    ("", None),
]


@pytest.mark.parametrize(
    "endpoint_url, expected_provider",
    S3_COMPATIBLE_PROVIDER_TEST_CASES,
)
def test_resolve_s3_provider(endpoint_url, expected_provider):
    """Tests the dispatcher returns the right provider name (or None)."""
    handler = S3Handler()
    assert handler._resolve_s3_provider(endpoint_url) == expected_provider


# Per-endpoint expectation for the boto3 ``Config`` that ``init_boto`` builds.
# ``user_agent_extra`` must always be ``wandb/<version>``; the virtual-hosted
# ``addressing_style`` switch only fires for recognized S3-compatible non-AWS
# endpoints.
INIT_BOTO_CONFIG_CASES = [
    # AWS S3 (no endpoint override): UA tagged, no addressing-style override.
    (None, False),
    # AWS-hosted S3 endpoint: UA tagged, no addressing-style override.
    ("https://s3.amazonaws.com", False),
    # Recognized non-AWS providers: UA tagged + virtual-hosted addressing.
    ("https://cwobject.com", True),
    ("https://s3.us-west-004.backblazeb2.com", True),
    ("https://my-bucket.s3.us-west-004.backblazeb2.com", True),
]


@pytest.mark.parametrize(
    "endpoint_url, expect_virtual_addressing",
    INIT_BOTO_CONFIG_CASES,
)
def test_init_boto_config(monkeypatch, endpoint_url, expect_virtual_addressing):
    """Tests that ``init_boto`` builds a boto3 ``Config`` with the right shape.

    Two invariants are checked:

    1. ``user_agent_extra`` is set to ``wandb/<version>`` for *every* endpoint
       (AWS or otherwise) so server-side request logs can identify the W&B SDK
       as the caller regardless of S3 backend.
    2. ``addressing_style="virtual"`` is set only for endpoints the dispatcher
       recognizes as S3-compatible non-AWS providers.
    """
    # ``init_boto`` requires boto3/botocore (the optional ``wandb[aws]`` extra);
    # skip cleanly if they are not installed in the test environment.
    pytest.importorskip("boto3")
    pytest.importorskip("botocore")

    monkeypatch.delenv("AWS_REGION", raising=False)
    if endpoint_url is None:
        monkeypatch.delenv("AWS_S3_ENDPOINT_URL", raising=False)
    else:
        monkeypatch.setenv("AWS_S3_ENDPOINT_URL", endpoint_url)

    handler = S3Handler()
    s3 = handler.init_boto()
    config = s3.meta.client.meta.config

    assert config.user_agent_extra == f"wandb/{wandb.__version__}"

    s3_config = config.s3 or {}
    if expect_virtual_addressing:
        assert s3_config.get("addressing_style") == "virtual"
    else:
        assert "addressing_style" not in s3_config
