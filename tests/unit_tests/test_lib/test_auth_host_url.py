import pytest
from wandb.sdk.lib.wbauth.host_url import HostUrl


def test_validates_url():
    with pytest.raises(ValueError):
        HostUrl("invalid")


@pytest.mark.parametrize(
    "raw_url",
    (
        "https://api.wandb.ai",
        "https://api.wandb.ai/",
        "https://api.wandb.ai//",
    ),
)
def test_normalizes_url(raw_url: str):
    url = HostUrl(raw_url)

    assert url.is_same_url(raw_url)
    assert not url.url.endswith("/")


def test_repr():
    assert repr(HostUrl("https://some-url")) == "HostUrl('https://some-url')"
