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


def test_app_url_explicit():
    url = HostUrl("https://api", app_url="https://my-ui")

    assert url.app_url == "https://my-ui"


def test_app_url_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("WANDB_APP_URL", "https://my-ui")
    url = HostUrl("https://api")

    assert url.app_url == "https://my-ui"


def test_app_url_default():
    url = HostUrl("https://api.wandb.ai")

    assert url.app_url == "https://wandb.ai"


@pytest.mark.parametrize("host", ["forge.coreweave.com", "qa.forge.coreweave.com"])
def test_forge_api_url(host):
    url = HostUrl(f"https://{host}/api/wandb/")

    assert url.url == f"https://{host}/api/wandb"
    assert not url.is_same_url("https://api.wandb.ai")


@pytest.mark.parametrize("host", ["forge.coreweave.com", "qa.forge.coreweave.com"])
@pytest.mark.parametrize("path", ["", "/", "/wandb", "/graphql"])
def test_forge_ui_url_is_not_an_api_url(host, path):
    with pytest.raises(ValueError, match=f"https://{host}/api/wandb"):
        HostUrl(f"https://{host}{path}")


def test_forge_api_requires_https():
    with pytest.raises(ValueError, match="https://forge.coreweave.com/api/wandb"):
        HostUrl("http://forge.coreweave.com/api/wandb")
