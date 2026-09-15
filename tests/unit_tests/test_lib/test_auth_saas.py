import pytest
from wandb.sdk.lib.wbauth import saas


@pytest.mark.parametrize(
    "url, expected",
    [
        ("https://wandb.ai", True),
        ("https://api.wandb.ai", True),
        ("https://api.qa.wandb.ai", True),
        ("https://forge.coreweave.com/api/wandb", True),
        ("https://qa.forge.coreweave.com/api/wandb", True),
        ("https://notwandb.ai", False),
        ("https://api.wandb.ai.example.org", False),
        ("https://api.wandb.io", False),
        ("https://coreweave.com", False),
        ("https://other.coreweave.com", False),
        ("https://other.forge.coreweave.com", False),
        ("https://forge.coreweave.com.example.org", False),
        ("https://forge.coreweave.com@other.example", False),
    ],
)
def test_is_wandb_domain(url, expected):
    assert saas.is_wandb_domain(url) is expected
