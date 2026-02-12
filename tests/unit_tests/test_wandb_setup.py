from unittest.mock import MagicMock

from wandb.errors import CommError
from wandb.sdk.wandb_setup import _WandbSetup


def _load_user_settings(server, entity=None):
    setup = MagicMock(spec=_WandbSetup)
    setup._server = server
    setup.viewer = server.viewer
    return _WandbSetup._load_user_settings(setup, entity=entity)


class TestLoadUserSettingsCodeSaving:
    def test_entity_scoped_policy(self):
        server = MagicMock()
        server._flags = {}
        server.viewer = {}
        server._api.entity_code_saving_enabled.return_value = True

        result = _load_user_settings(server, entity="my-team")

        assert result is not None
        assert result["save_code"] is True

    def test_entity_policy_overrides_viewer_flags(self):
        server = MagicMock()
        server._flags = {"code_saving_enabled": True}
        server.viewer = {}
        server._api.entity_code_saving_enabled.return_value = False

        result = _load_user_settings(server, entity="my-team")

        assert result is not None
        assert result["save_code"] is False

    def test_entity_policy_true_overrides_default_entity_false(self):
        server = MagicMock()
        server._flags = {"code_saving_enabled": False}
        server.viewer = {}
        server._api.entity_code_saving_enabled.return_value = True

        result = _load_user_settings(server, entity="my-team")

        assert result is not None
        assert result["save_code"] is True

    def test_uses_default_entity_viewer_flags_when_entity_not_explicit(self):
        server = MagicMock()
        server._flags = {"code_saving_enabled": True}
        server.viewer = {}

        result = _load_user_settings(server)

        assert result is not None
        assert result["save_code"] is True
        server._api.entity_code_saving_enabled.assert_not_called()

    def test_uses_default_entity_viewer_flags_false_when_entity_not_explicit(self):
        server = MagicMock()
        server._flags = {"code_saving_enabled": False}
        server.viewer = {}

        result = _load_user_settings(server)

        assert result is not None
        assert result["save_code"] is False
        server._api.entity_code_saving_enabled.assert_not_called()

    def test_no_code_saving_policy_when_entity_query_fails(self):
        server = MagicMock()
        server._flags = {"code_saving_enabled": True}
        server.viewer = {}
        server._api.entity_code_saving_enabled.side_effect = CommError("server error")

        result = _load_user_settings(server, entity="my-team")

        assert result is not None
        assert "save_code" not in result
