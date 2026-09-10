from __future__ import annotations

import json
import pathlib

import pytest
from wandb.sdk.lib.wbauth import identity_token_file
from wandb.sdk.lib.wbauth.host_url import HostUrl


def _account(host: str, org: str | None = None) -> identity_token_file.Account:
    return identity_token_file.Account(
        id_token=f"{org or host}-id-token",
        refresh_token="refresh-token",
        token_endpoint="https://idp.example.com/token",
        client_id="wandb-cli",
        host=host,
        org=org,
    )


def test_default_path_uses_config_dir(tmp_path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("WANDB_CONFIG_DIR", str(tmp_path))

    assert identity_token_file.default_path() == tmp_path / "identity_token.json"


def test_save_is_private_and_atomic(tmp_path: pathlib.Path):
    accounts = identity_token_file.Accounts()
    accounts.add(_account("https://api.wandb.ai", "acme"))
    path = tmp_path / "nested" / "identity_token.json"

    accounts.save(path)

    assert (path.stat().st_mode & 0o777) == 0o600
    assert json.loads(path.read_text()) == {
        "version": 1,
        "active": "https://api.wandb.ai#acme",
        "accounts": {
            "https://api.wandb.ai#acme": {
                "id_token": "acme-id-token",
                "refresh_token": "refresh-token",
                "token_endpoint": "https://idp.example.com/token",
                "client_id": "wandb-cli",
                "host": "https://api.wandb.ai",
                "org": "acme",
            }
        },
    }


def test_add_keeps_accounts_for_other_hosts(tmp_path: pathlib.Path):
    path = tmp_path / "identity_token.json"
    accounts = identity_token_file.Accounts()
    accounts.add(_account("https://wandb.corp.example.com"))
    accounts.save(path)

    reloaded = identity_token_file.load(path)
    reloaded.add(_account("https://api.wandb.ai", "acme"))
    reloaded.save(path)

    saved = identity_token_file.load(path)
    assert set(saved.accounts) == {
        "https://wandb.corp.example.com",
        "https://api.wandb.ai#acme",
    }
    assert saved.active == "https://api.wandb.ai#acme"


def test_for_host_selects_matching_account():
    accounts = identity_token_file.Accounts()
    accounts.add(_account("https://api.wandb.ai", "acme"))
    accounts.add(_account("https://wandb.corp.example.com"))

    account = accounts.for_host(HostUrl("https://wandb.corp.example.com/"))

    assert account is not None
    assert account.id_token == "https://wandb.corp.example.com-id-token"


def test_for_host_prefers_active_account():
    accounts = identity_token_file.Accounts()
    accounts.add(_account("https://api.wandb.ai", "acme"))
    accounts.add(_account("https://api.wandb.ai", "zeta"))

    account = accounts.for_host(HostUrl("https://api.wandb.ai"))

    assert account is not None
    assert account.org == "zeta"


def test_for_host_rejects_ambiguous_accounts():
    accounts = identity_token_file.Accounts()
    accounts.add(_account("https://api.wandb.ai", "acme"))
    accounts.add(_account("https://api.wandb.ai", "zeta"))
    accounts.active = None

    with pytest.raises(identity_token_file.AmbiguousAccountError, match="acme, zeta"):
        accounts.for_host(HostUrl("https://api.wandb.ai"))


def test_load_rejects_bare_jwt(tmp_path: pathlib.Path):
    path = tmp_path / "identity_token.json"
    path.write_text("header.payload.signature")

    with pytest.raises(identity_token_file.InvalidIdentityTokenFileError):
        identity_token_file.load(path)


def test_load_rejects_newer_file_format(tmp_path: pathlib.Path):
    path = tmp_path / "identity_token.json"
    path.write_text(json.dumps({"version": 2, "accounts": {}}))

    with pytest.raises(
        identity_token_file.InvalidIdentityTokenFileError,
        match="Upgrade wandb",
    ):
        identity_token_file.load(path)


def test_load_rejects_account_without_id_token(tmp_path: pathlib.Path):
    path = tmp_path / "identity_token.json"
    path.write_text(
        json.dumps({"version": 1, "accounts": {"https://api.wandb.ai": {}}})
    )

    with pytest.raises(
        identity_token_file.InvalidIdentityTokenFileError,
        match="id_token",
    ):
        identity_token_file.load(path)


def test_load_or_empty_warns_about_unreadable_file(
    tmp_path: pathlib.Path,
    capsys: pytest.CaptureFixture,
):
    path = tmp_path / "identity_token.json"
    path.write_text("not json")

    accounts = identity_token_file.load_or_empty(path)

    assert accounts.accounts == {}
    assert "Replacing unreadable saved credentials" in capsys.readouterr().err


def test_load_or_empty_is_quiet_for_missing_file(
    tmp_path: pathlib.Path,
    capsys: pytest.CaptureFixture,
):
    accounts = identity_token_file.load_or_empty(tmp_path / "missing.json")

    assert accounts.accounts == {}
    assert capsys.readouterr().err == ""
