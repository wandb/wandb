from __future__ import annotations

import configparser
import json
import pathlib

import pytest
from wandb.apis.public.service_api import AuthenticateResponse, ServiceApi
from wandb.cli import cli
from wandb.sdk.lib.wbauth import sso_login


@pytest.fixture
def fake_pkce_login(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    calls: list[dict] = []

    def fake_login_with_pkce(host, *, org=None, open_browser=True):
        calls.append({"host": host, "org": org, "open_browser": open_browser})
        return sso_login.TokenSet(
            id_token="fake-id-token",
            refresh_token="fake-refresh-token",
            token_endpoint="https://idp.example.com/token",
            client_id="wandb-cli",
            host=host.url,
        )

    monkeypatch.setattr(cli.sso_login, "login_with_pkce", fake_login_with_pkce)
    monkeypatch.setattr(
        ServiceApi,
        "authenticate",
        lambda self: AuthenticateResponse(),
    )
    return calls


def _read_system_settings(path: pathlib.Path) -> dict[str, str]:
    parser = configparser.ConfigParser()
    parser.read(path)
    return dict(parser.items(section="default"))


def test_sso_login_help(runner):
    result = runner.invoke(cli.cli, ["login", "sso", "--help"])

    assert result.exit_code == 0
    assert "identity provider" in result.output
    assert "--host" in result.output
    assert "--org" in result.output


def test_login_help_keeps_api_key_options(runner):
    result = runner.invoke(cli.cli, ["login", "--help"])

    assert result.exit_code == 0
    assert "--host" in result.output
    assert "--verify" in result.output
    assert "--relogin" in result.output


def test_sso_login_writes_identity_token_file(
    runner,
    local_settings,
    tmp_path: pathlib.Path,
    fake_pkce_login: list[dict],
):
    token_path = tmp_path / "identity_token.json"
    system_settings = cli.wandb_setup.singleton().settings.read_system_settings()
    system_settings.set("api_key", "old-api-key", globally=True)
    system_settings.save()

    result = runner.invoke(
        cli.cli,
        [
            "login",
            "sso",
            "--host",
            "https://my-wandb.example.com",
            "--org",
            "acme",
            "--identity-token-file",
            str(token_path),
        ],
    )

    assert result.exit_code == 0, result.output
    assert len(fake_pkce_login) == 1
    assert fake_pkce_login[0]["host"].is_same_url("https://my-wandb.example.com")
    assert fake_pkce_login[0]["org"] == "acme"
    assert fake_pkce_login[0]["open_browser"] is True

    assert token_path.exists()
    assert json.loads(token_path.read_text()) == {
        "id_token": "fake-id-token",
        "refresh_token": "fake-refresh-token",
        "token_endpoint": "https://idp.example.com/token",
        "client_id": "wandb-cli",
        "host": "https://my-wandb.example.com",
    }

    system_settings_path = pathlib.Path(
        cli.wandb_setup.singleton().settings.settings_system
    )
    settings = _read_system_settings(system_settings_path)
    assert "api_key" not in settings
    assert settings["identity_token_file"] == str(token_path)
    assert settings["credentials_file"]
    assert settings["base_url"] == "https://my-wandb.example.com"


def test_sso_login_default_host_clears_base_url(
    runner,
    local_settings,
    tmp_path: pathlib.Path,
    fake_pkce_login: list[dict],
):
    system_settings = cli.wandb_setup.singleton().settings.read_system_settings()
    system_settings.set("base_url", "https://old-dedicated.example.com", globally=True)
    system_settings.save()

    result = runner.invoke(
        cli.cli,
        [
            "login",
            "sso",
            "--host",
            "https://api.wandb.ai",
            "--identity-token-file",
            str(tmp_path / "identity_token.json"),
        ],
    )

    assert result.exit_code == 0, result.output
    system_settings_path = pathlib.Path(
        cli.wandb_setup.singleton().settings.settings_system
    )
    settings = _read_system_settings(system_settings_path)
    assert "base_url" not in settings


def test_sso_login_requires_org_or_host(runner, local_settings):
    result = runner.invoke(cli.cli, ["login", "sso"])

    assert result.exit_code == 2
    assert "--org" in result.output
    assert "--host" in result.output


def test_sso_login_org_only_uses_configured_base_url(
    runner,
    local_settings,
    tmp_path: pathlib.Path,
    fake_pkce_login: list[dict],
):
    system_settings = cli.wandb_setup.singleton().settings.read_system_settings()
    system_settings.set("base_url", "https://api.wandb.ai", globally=True)
    system_settings.save()
    cli.wandb_setup.singleton().settings.update_from_system_settings()

    result = runner.invoke(
        cli.cli,
        [
            "login",
            "sso",
            "--org",
            "acme",
            "--identity-token-file",
            str(tmp_path / "identity_token.json"),
        ],
    )

    assert result.exit_code == 0, result.output
    assert len(fake_pkce_login) == 1
    assert fake_pkce_login[0]["host"].is_same_url("https://api.wandb.ai")
    assert fake_pkce_login[0]["org"] == "acme"


def test_sso_login_preserves_existing_file_if_verification_fails(
    runner,
    local_settings,
    tmp_path: pathlib.Path,
    fake_pkce_login: list[dict],
    monkeypatch: pytest.MonkeyPatch,
):
    def fail_verification(self):
        raise RuntimeError("verification failed")

    monkeypatch.setattr(ServiceApi, "authenticate", fail_verification)
    token_path = tmp_path / "identity_token.json"
    token_path.write_text("existing credentials")

    result = runner.invoke(
        cli.cli,
        [
            "login",
            "sso",
            "--host",
            "https://my-wandb.example.com",
            "--identity-token-file",
            str(token_path),
        ],
    )

    assert result.exit_code != 0
    assert token_path.read_text() == "existing credentials"


def test_sso_login_fails_if_settings_cannot_be_saved(
    runner,
    local_settings,
    tmp_path: pathlib.Path,
    fake_pkce_login: list[dict],
    monkeypatch: pytest.MonkeyPatch,
):
    def fail_save(_self):
        raise cli.settings_file.SaveSettingsError("read-only")

    monkeypatch.setattr(cli.settings_file.SettingsFiles, "save", fail_save)

    result = runner.invoke(
        cli.cli,
        [
            "login",
            "sso",
            "--host",
            "https://my-wandb.example.com",
            "--identity-token-file",
            str(tmp_path / "identity_token.json"),
        ],
    )

    assert result.exit_code != 0
    assert "Logged in to" not in result.output
