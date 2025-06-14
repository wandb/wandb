import pytest
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
