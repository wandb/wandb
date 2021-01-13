import os
import time

from wandb import wandb_lib
from wandb import env


def test_write_netrc():
    api_key = "X" * 40
    wandb_lib.apikey.write_netrc("http://localhost", "vanpelt", api_key)
    with open(os.path.expanduser("~/.netrc")) as f:
        assert f.read() == (
            "machine localhost\n" "  login vanpelt\n" "  password %s\n" % api_key
        )


def test_token_store():
    token_store = wandb_lib.oidc.TokenStore("test")
    assert token_store.version == len(wandb_lib.oidc.TokenStore.SCHEMA)
    assert token_store.tokens == []
    token_store.save({"foo": "bar"})
    assert len(token_store.tokens) == 1
    token_store = wandb_lib.oidc.TokenStore("test", "new_client_id")
    token_store.save({"foo": "bar"})
    assert len(token_store.tokens) == 2


def test_session_manager(live_mock_server, capsys):
    try:
        os.environ[env.DISCOVERY_URL] = (
            live_mock_server.base_url + "/openid_configuration"
        )
        session_manager = wandb_lib.oidc.SessionManager()
        session_manager.prompt_login(attempt_launch_browser=False)
        _, err = capsys.readouterr()
        print(err)
        device_url = live_mock_server.base_url + "/device"
        assert device_url in err
        assert "YYVM-DGMD" in err
        assert "Authentication successful!"
        ctx = live_mock_server.get_ctx()
        assert ctx["device_code_calls"] == 3
        assert (
            session_manager.token.get("refresh_token")
            == "JUSkVOek0xTlRsRFEwUXlNVU0yTXpReU1EUXdSRGcyUkVVNE"
        )
    finally:
        del os.environ[env.DISCOVERY_URL]


def test_session_manager_refresh(live_mock_server):
    try:
        os.environ[env.DISCOVERY_URL] = (
            live_mock_server.base_url + "/openid_configuration"
        )
        os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"
        session_manager = wandb_lib.oidc.SessionManager()
        session_manager.token_saver(
            {
                "access_token": "XXXX",
                "refresh_token": "REFRESH ME",
                "scope": ["openid"],
                "expires_at": time.time() - 10,
            }
        )
        res = session_manager.session().get(live_mock_server.base_url + "/headers")
        assert res.json()["Authorization"] == "Bearer REFRESHED_ID_TOKEN"
    finally:
        del os.environ["OAUTHLIB_INSECURE_TRANSPORT"]
        del os.environ[env.DISCOVERY_URL]
