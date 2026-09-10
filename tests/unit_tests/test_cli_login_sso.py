from __future__ import annotations

import configparser
import json
import pathlib

import pytest
from wandb.apis.public.service_api import AuthenticateResponse, ServiceApi
from wandb.cli import cli
from wandb.sdk.lib.wbauth import identity_token_file


@pytest.fixture
def fake_pkce_login(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    calls: list[dict] = []

    def fake_login_with_pkce(host, *, org=None, expected=None):
        calls.append({"host": host, "org": org, "expected": expected})
        return identity_token_file.Account(
            id_token="fake-id-token",
            refresh_token="fake-refresh-token",
            token_endpoint="https://idp.example.com/token",
            client_id="wandb-cli",
            host=host.url,
            org=org,
        )

    monkeypatch.setattr(cli.sso_login, "login_with_pkce", fake_login_with_pkce)
    monkeypatch.setattr(
        ServiceApi,
        "authenticate",
        lambda self: AuthenticateResponse(),
    )
    return calls


@pytest.fixture
def fake_device_code_login(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    calls: list[dict] = []

    def fake_login_with_device_code(host, *, org=None, expected=None):
        calls.append({"host": host, "org": org, "expected": expected})
        return identity_token_file.Account(
            id_token="fake-device-id-token",
            refresh_token="fake-device-refresh-token",
            token_endpoint="https://idp.example.com/token",
            client_id="wandb-cli",
            host=host.url,
            org=org,
        )

    monkeypatch.setattr(
        cli.sso_login,
        "login_with_device_code",
        fake_login_with_device_code,
    )
    monkeypatch.setattr(
        ServiceApi,
        "authenticate",
        lambda self: AuthenticateResponse(),
    )
    return calls


@pytest.fixture
def fake_org_picker(monkeypatch: pytest.MonkeyPatch) -> list:
    """Stands in for the W&B page that lists the user's organizations."""
    calls = []

    def fake_select_organization(host):
        calls.append(host)
        return "picked-org"

    monkeypatch.setattr(cli.sso_login, "select_organization", fake_select_organization)
    return calls


@pytest.fixture
def saas_base_url(local_settings):
    """Points the CLI at multi-tenant SaaS, as a fresh install would be."""
    system_settings = cli.wandb_setup.singleton().settings.read_system_settings()
    system_settings.set("base_url", "https://api.wandb.ai", globally=True)
    system_settings.save()
    cli.wandb_setup.singleton().settings.update_from_system_settings()


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
    assert "--issuer" in result.output
    assert "--client-id" in result.output
    assert "--use-device-code" in result.output


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
            "--identity-token-file",
            str(token_path),
        ],
    )

    assert result.exit_code == 0, result.output
    assert len(fake_pkce_login) == 1
    assert fake_pkce_login[0]["host"].is_same_url("https://my-wandb.example.com")
    assert fake_pkce_login[0]["org"] is None

    assert token_path.exists()
    assert json.loads(token_path.read_text()) == {
        "version": 1,
        "active": "https://my-wandb.example.com",
        "accounts": {
            "https://my-wandb.example.com": {
                "id_token": "fake-id-token",
                "refresh_token": "fake-refresh-token",
                "token_endpoint": "https://idp.example.com/token",
                "client_id": "wandb-cli",
                "host": "https://my-wandb.example.com",
            }
        },
    }

    system_settings_path = pathlib.Path(
        cli.wandb_setup.singleton().settings.settings_system
    )
    settings = _read_system_settings(system_settings_path)
    assert "api_key" not in settings
    assert settings["identity_token_file"] == str(token_path)
    assert settings["base_url"] == "https://my-wandb.example.com"


def test_sso_login_uses_device_code(
    runner,
    local_settings,
    tmp_path: pathlib.Path,
    fake_device_code_login: list[dict],
    fake_pkce_login: list[dict],
):
    token_path = tmp_path / "identity_token.json"

    result = runner.invoke(
        cli.cli,
        [
            "login",
            "sso",
            "--host",
            "https://my-wandb.example.com",
            "--use-device-code",
            "--identity-token-file",
            str(token_path),
        ],
    )

    assert result.exit_code == 0, result.output
    assert fake_pkce_login == []
    assert len(fake_device_code_login) == 1
    assert fake_device_code_login[0]["host"].is_same_url("https://my-wandb.example.com")


def test_sso_login_rejects_saas_as_a_host(runner, local_settings):
    result = runner.invoke(
        cli.cli,
        ["login", "sso", "--host", "https://api.wandb.ai"],
    )

    assert result.exit_code == 2
    assert "serves many organizations" in result.output


@pytest.mark.parametrize(
    "extra",
    [
        ["--org", "acme"],
        ["--issuer", "https://idp.example.com"],
        ["--client-id", "wandb-cli"],
    ],
)
def test_sso_login_rejects_host_with_org_flags(runner, local_settings, extra):
    result = runner.invoke(
        cli.cli,
        ["login", "sso", "--host", "https://my-wandb.example.com", *extra],
    )

    assert result.exit_code == 2
    assert "resolves its own identity provider" in result.output


@pytest.mark.parametrize(
    ("flags", "missing"),
    [
        (["--org", "acme"], "--issuer, --client-id"),
        (["--org", "acme", "--issuer", "https://idp.example.com"], "--client-id"),
        (["--org", "acme", "--client-id", "wandb-cli"], "--issuer"),
        (["--issuer", "https://idp.example.com", "--client-id", "wandb-cli"], "--org"),
    ],
)
def test_sso_login_org_requires_its_identity_provider(
    runner,
    saas_base_url,
    fake_pkce_login: list[dict],
    fake_org_picker: list,
    flags,
    missing,
):
    result = runner.invoke(cli.cli, ["login", "sso", *flags])

    assert result.exit_code == 2
    assert f"Add {missing}" in result.output
    assert fake_pkce_login == []
    assert fake_org_picker == []


def test_sso_login_with_explicit_org_checks_the_named_provider(
    runner,
    saas_base_url,
    tmp_path: pathlib.Path,
    fake_pkce_login: list[dict],
    fake_org_picker: list,
):
    result = runner.invoke(
        cli.cli,
        [
            "login",
            "sso",
            "--org",
            "acme",
            "--issuer",
            "https://idp.example.com",
            "--client-id",
            "wandb-cli",
            "--identity-token-file",
            str(tmp_path / "identity_token.json"),
        ],
    )

    assert result.exit_code == 0, result.output
    assert fake_org_picker == []
    assert len(fake_pkce_login) == 1
    assert fake_pkce_login[0]["host"].is_same_url("https://api.wandb.ai")
    assert fake_pkce_login[0]["org"] == "acme"
    assert fake_pkce_login[0]["expected"] == cli.sso_login.ExpectedIdp(
        issuer="https://idp.example.com",
        client_id="wandb-cli",
    )

    # The default host is left implicit rather than pinned in the settings.
    system_settings_path = pathlib.Path(
        cli.wandb_setup.singleton().settings.settings_system
    )
    assert "base_url" not in _read_system_settings(system_settings_path)


def test_sso_login_without_flags_picks_an_org_on_saas(
    runner,
    saas_base_url,
    tmp_path: pathlib.Path,
    fake_pkce_login: list[dict],
    fake_org_picker: list,
):
    result = runner.invoke(
        cli.cli,
        [
            "login",
            "sso",
            "--identity-token-file",
            str(tmp_path / "identity_token.json"),
        ],
    )

    assert result.exit_code == 0, result.output
    assert len(fake_org_picker) == 1
    assert fake_org_picker[0].is_same_url("https://api.wandb.ai")
    assert len(fake_pkce_login) == 1
    assert fake_pkce_login[0]["org"] == "picked-org"
    assert fake_pkce_login[0]["expected"] is None


def test_sso_login_without_flags_skips_the_picker_on_a_dedicated_instance(
    runner,
    local_settings,
    tmp_path: pathlib.Path,
    fake_pkce_login: list[dict],
    fake_org_picker: list,
):
    system_settings = cli.wandb_setup.singleton().settings.read_system_settings()
    system_settings.set("base_url", "https://my-wandb.example.com", globally=True)
    system_settings.save()
    cli.wandb_setup.singleton().settings.update_from_system_settings()

    result = runner.invoke(
        cli.cli,
        [
            "login",
            "sso",
            "--identity-token-file",
            str(tmp_path / "identity_token.json"),
        ],
    )

    assert result.exit_code == 0, result.output
    assert fake_org_picker == []
    assert len(fake_pkce_login) == 1
    assert fake_pkce_login[0]["org"] is None


def test_sso_login_uses_device_code_after_the_picker(
    runner,
    saas_base_url,
    tmp_path: pathlib.Path,
    fake_device_code_login: list[dict],
    fake_pkce_login: list[dict],
    fake_org_picker: list,
):
    result = runner.invoke(
        cli.cli,
        [
            "login",
            "sso",
            "--use-device-code",
            "--identity-token-file",
            str(tmp_path / "identity_token.json"),
        ],
    )

    assert result.exit_code == 0, result.output
    assert fake_pkce_login == []
    assert len(fake_org_picker) == 1
    assert len(fake_device_code_login) == 1
    assert fake_device_code_login[0]["org"] == "picked-org"


def test_sso_login_replaces_unreadable_credentials(
    runner,
    local_settings,
    tmp_path: pathlib.Path,
    fake_pkce_login: list[dict],
):
    token_path = tmp_path / "identity_token.json"
    token_path.write_text("header.payload.signature")

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

    assert result.exit_code == 0, result.output
    assert "Replacing unreadable saved credentials" in result.output
    assert set(json.loads(token_path.read_text())["accounts"]) == {
        "https://my-wandb.example.com"
    }


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
