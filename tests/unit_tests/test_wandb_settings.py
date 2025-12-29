import copy
import json
import os
import pathlib
import platform
import subprocess
import sys
import tempfile
from unittest import mock

import pytest
import wandb
from pydantic.version import VERSION as PYDANTIC_VERSION
from wandb import Settings
from wandb.errors import UsageError
from wandb.sdk.lib.credentials import DEFAULT_WANDB_CREDENTIALS_FILE
from wandb.sdk.lib.run_moment import RunMoment

is_pydantic_v1 = int(PYDANTIC_VERSION[0]) == 1


@pytest.mark.skipif(is_pydantic_v1, reason="Pydantic v1 allows extra fields")
def test_unexpected_arguments():
    with pytest.raises(ValueError):
        Settings(lol=False)


def test_mapping_interface():
    settings = Settings()
    for _ in settings:
        pass


def test_is_local():
    s = Settings(base_url="https://api.wandb.ai")
    assert s.is_local is False


@pytest.mark.skipif(is_pydantic_v1, reason="Pydantic v1 does type coercion")
def test_invalid_field_type():
    with pytest.raises(ValueError):
        Settings(api_key=271828)  # must be a string


@pytest.mark.parametrize(
    "tags,expected_error",
    [
        ([""], "Tags must be between 1 and 64 characters"),
        (["a" * 65], "Tags must be between 1 and 64 characters"),
        (
            ["valid", "a" * 65, "another_valid"],
            "Tags must be between 1 and 64 characters",
        ),
    ],
)
def test_run_tags_validation_errors(tags, expected_error):
    """Test that invalid run tags raise appropriate errors."""
    with pytest.raises(ValueError, match=expected_error):
        Settings(run_tags=tags)


@pytest.mark.parametrize(
    "tags,expected",
    [
        (["valid", "tag2"], ("valid", "tag2")),
        (["a" * 64], ("a" * 64,)),
        ("single_tag", ("single_tag",)),
        (None, None),
    ],
)
def test_run_tags_validation_success(tags, expected):
    """Test that valid run tags are accepted and converted appropriately."""
    settings = Settings(run_tags=tags)
    if expected is None:
        assert settings.run_tags is None
    else:
        assert settings.run_tags == expected
        if tags == ["a" * 64]:
            assert len(settings.run_tags[0]) == 64


def test_program_python_m():
    with tempfile.TemporaryDirectory() as tmpdir:
        path_module = os.path.join(tmpdir, "module")
        os.mkdir(path_module)
        with open(os.path.join(path_module, "lib.py"), "w") as f:
            f.write(
                "import wandb\n\n\n"
                "if __name__ == '__main__':\n"
                "    run = wandb.init(mode='offline')\n"
                "    print(run.settings.program)\n"
            )
        output = subprocess.check_output(
            [sys.executable, "-m", "module.lib"], cwd=tmpdir
        )
        assert "-m module.lib" in output.decode("utf-8")


@pytest.mark.skip(reason="Unskip once api_key validation is restored")
def test_local_api_key_validation():
    with pytest.raises(UsageError):
        wandb.Settings(
            api_key="local-87eLxjoRhY6u2ofg63NAJo7rVYHZo4NGACOvpSsF",
            base_url="https://api.wandb.ai",
        )


def test_run_urls():
    base_url = "https://my.cool.site.com"
    entity = "me"
    project = "lol"
    run_id = "123"
    s = Settings(
        base_url=base_url,
        entity=entity,
        project=project,
        run_id=run_id,
    )
    assert s.project_url == f"{base_url}/{entity}/{project}"
    assert s.run_url == f"{base_url}/{entity}/{project}/runs/{run_id}"


def test_offline():
    test_settings = Settings()
    assert test_settings._offline is False
    test_settings.mode = "offline"
    assert test_settings._offline is True
    test_settings.mode = "dryrun"
    assert test_settings._offline is True


def test_silent():
    s = Settings()
    s.update_from_env_vars({"WANDB_SILENT": "true"})
    assert s.silent is True


def test_noop():
    test_settings = Settings()
    test_settings.mode = "disabled"
    assert test_settings._noop is True


def test_get_base_url():
    s = Settings()
    assert s.base_url == "https://api.wandb.ai"


def test_base_url_validation():
    s = Settings()
    s.base_url = "https://api.wandb.space"
    with pytest.raises(ValueError):
        s.base_url = "new"


def test_app_url_default():
    s = Settings(base_url="https://api.wandb.ai")
    assert s.app_url == "https://wandb.ai"


def test_app_url_override():
    s = Settings(base_url="https://api.wandb.ai", app_url_override="https://my-ui")
    assert s.app_url == "https://my-ui"


def test_get_non_existent_attribute():
    s = Settings()
    with pytest.raises(AttributeError):
        s.missing  # noqa: B018


def test_set_extra_attribute():
    s = Settings()
    with pytest.raises(ValueError):
        s.missing = "nope"


def test_ignore_globs():
    s = Settings()
    assert s.ignore_globs == ()


def test_ignore_globs_explicit():
    s = Settings(ignore_globs=["foo"])
    assert s.ignore_globs == ("foo",)


def test_ignore_globs_env():
    s = Settings()
    s.update_from_env_vars({"WANDB_IGNORE_GLOBS": "foo"})
    assert s.ignore_globs == ("foo",)

    s = Settings()
    s.update_from_env_vars({"WANDB_IGNORE_GLOBS": "foo,bar"})
    assert s.ignore_globs == (
        "foo",
        "bar",
    )


def test_token_file_env():
    s = Settings()
    s.update_from_env_vars({"WANDB_IDENTITY_TOKEN_FILE": "jwt.txt"})
    assert s.identity_token_file == ("jwt.txt")


def test_credentials_file_env():
    s = Settings()
    assert s.credentials_file == str(DEFAULT_WANDB_CREDENTIALS_FILE)

    s = Settings()
    s.update_from_env_vars({"WANDB_CREDENTIALS_FILE": "/tmp/credentials.json"})
    assert s.credentials_file == "/tmp/credentials.json"


def test_quiet():
    s = Settings()
    assert not s.quiet
    s = Settings(quiet=True)
    assert s.quiet
    s = Settings()
    s.update_from_env_vars({"WANDB_QUIET": "false"})
    assert not s.quiet


@pytest.mark.skip(reason="I need to make my mock work properly with new settings")
def test_ignore_globs_settings(local_settings):
    with open(os.path.join(os.getcwd(), ".config", "wandb", "settings"), "w") as f:
        f.write(
            """[default]
ignore_globs=foo,bar"""
        )
    s = Settings(_files=True)
    assert s.ignore_globs == (
        "foo",
        "bar",
    )


def test_copy():
    s = Settings()
    s.base_url = "https://changed.local"
    s2 = copy.copy(s)
    assert s2.base_url == "https://changed.local"
    s.base_url = "https://not.changed.local"
    assert s.base_url == "https://not.changed.local"
    assert s2.base_url == "https://changed.local"


def test_update_linked_properties():
    s = Settings()
    # sync_dir depends, among other things, on run_mode
    assert s.mode == "online"
    assert s.run_mode == "run"
    assert ("offline-run" not in s.sync_dir) and ("run" in s.sync_dir)
    s.mode = "offline"
    assert s.mode == "offline"
    assert s.run_mode == "offline-run"
    assert "offline-run" in s.sync_dir


def test_copy_update_linked_properties():
    s = Settings()
    assert s.mode == "online"
    assert s.run_mode == "run"
    assert ("offline-run" not in s.sync_dir) and ("run" in s.sync_dir)

    s2 = copy.copy(s)
    assert s2.mode == "online"
    assert s2.run_mode == "run"
    assert ("offline-run" not in s2.sync_dir) and ("run" in s2.sync_dir)

    s.mode = "offline"
    assert s.mode == "offline"
    assert s.run_mode == "offline-run"
    assert "offline-run" in s.sync_dir
    assert s2.mode == "online"
    assert s2.run_mode == "run"
    assert ("offline-run" not in s2.sync_dir) and ("run" in s2.sync_dir)

    s2.mode = "offline"
    assert s2.mode == "offline"
    assert s2.run_mode == "offline-run"
    assert "offline-run" in s2.sync_dir


def test_validate_mode():
    s = Settings()
    with pytest.raises(ValueError):
        s.mode = "goodprojo"
    with pytest.raises(ValueError):
        s.mode = "badmode"


@pytest.mark.parametrize(
    "url",
    [
        "https://api.wandb.ai",
        "https://wandb.ai.other.crazy.domain.com",
        "https://127.0.0.1",
        "https://localhost",
        "https://192.168.31.1:8080",
        "https://myhost:8888",  # fixme: should this be allowed?
    ],
)
def test_validate_base_url(url):
    s = Settings(base_url=url)
    assert s.base_url == url


@pytest.mark.parametrize(
    "url",
    [
        # wandb.ai-specific errors, should be https://api.wandb.ai
        "https://wandb.ai",
        "https://app.wandb.ai",
        "http://api.wandb.ai",  # insecure
        # only http(s) schemes are allowed
        "ftp://wandb.ai",
        # unsafe characters
        "http://host\t.ai",
        "http://host\n.ai",
        "http://host\r.ai",
        "gibberish",
        "LOL" * 100,
    ],
)
def test_validate_invalid_base_url(url):
    s = Settings()
    with pytest.raises(ValueError):
        s.base_url = url


@pytest.mark.parametrize(
    "url, processed_url",
    [
        ("https://host.com", "https://host.com"),
        ("https://host.com/", "https://host.com"),
        ("https://host.com///", "https://host.com"),
    ],
)
def test_preprocess_base_url(url, processed_url):
    s = Settings()
    s.base_url = url
    assert s.base_url == processed_url


@pytest.mark.parametrize(
    "setting",
    [
        "x_disable_meta",
        "x_disable_stats",
        "x_disable_viewer",
        "disable_code",
        "disable_git",
        "force",
        "label_disable",
        "launch",
        "quiet",
        "reinit",
        "relogin",
        "sagemaker_disable",
        "save_code",
        "show_colors",
        "show_emoji",
        "show_errors",
        "show_info",
        "show_warnings",
        "silent",
        "strict",
    ],
)
def test_preprocess_bool_settings(setting: str):
    with mock.patch.dict(os.environ, {"WANDB_" + setting.upper(): "true"}):
        s = Settings()
        s.update_from_env_vars(environ=os.environ)
        assert getattr(s, setting) is True


@pytest.mark.parametrize(
    "setting, value",
    [
        ("x_stats_open_metrics_endpoints", '{"DCGM":"http://localhvost"}'),
        (
            "x_stats_open_metrics_filters",
            '{"DCGM_FI_DEV_POWER_USAGE": {"pod": "dcgm-*"}}',
        ),
        (
            "x_extra_http_headers",
            '{"User-Agent": "foobar"}',
        ),
    ],
)
def test_preprocess_dict_settings(setting: str, value: str):
    with mock.patch.dict(os.environ, {"WANDB_" + setting.upper(): value}):
        s = Settings()
        s.update_from_env_vars(environ=os.environ)
        assert getattr(s, setting) == json.loads(value)


def test_wandb_dir():
    test_settings = Settings()
    assert os.path.abspath(test_settings.wandb_dir) == os.path.abspath("wandb")


def test_resume_fname():
    test_settings = Settings()
    assert test_settings.resume_fname == os.path.abspath(
        os.path.join(".", "wandb", "wandb-resume.json")
    )


def test_log_user():
    test_settings = Settings(run_id="test")
    _, run_dir, log_dir, fname = os.path.abspath(
        os.path.realpath(test_settings.log_user)
    ).rsplit(os.path.sep, 3)
    _, _, run_id = run_dir.split("-")
    assert run_id == test_settings.run_id
    assert log_dir == "logs"
    assert fname == "debug.log"


def test_log_internal():
    test_settings = Settings(run_id="test")
    _, run_dir, log_dir, fname = os.path.abspath(
        os.path.realpath(test_settings.log_internal)
    ).rsplit(os.path.sep, 3)
    _, _, run_id = run_dir.split("-")
    assert run_id == test_settings.run_id
    assert log_dir == "logs"
    assert fname == "debug-internal.log"


# --------------------------
# test static settings
# --------------------------


def test_settings_static():
    from wandb.sdk.internal.settings_static import SettingsStatic

    static_settings = SettingsStatic({})
    assert "base_url" in static_settings
    assert static_settings.base_url == "https://api.wandb.ai"


# --------------------------
# test run settings
# --------------------------


def test_silent_run(mock_run):
    test_settings = Settings()
    test_settings.silent = True
    assert test_settings.silent is True
    run = mock_run(settings=test_settings)
    assert run._settings.silent is True


def test_strict_run(mock_run):
    test_settings = Settings()
    test_settings.strict = True
    assert test_settings.strict is True
    run = mock_run(settings=test_settings)
    assert run._settings.strict is True


def test_show_info_run(mock_run):
    run = mock_run()
    assert run._settings.show_info is True


def test_show_info_false_run(mock_run):
    test_settings = Settings()
    test_settings.show_info = False
    run = mock_run(settings=test_settings)
    assert run._settings.show_info is False


def test_show_warnings_run(mock_run):
    test_settings = Settings()
    test_settings.show_warnings = True
    run = mock_run(settings=test_settings)
    assert run._settings.show_warnings is True


def test_not_jupyter(mock_run):
    run = mock_run()
    assert run._settings._jupyter is False


def test_resume_fname_run(mock_run):
    run = mock_run()
    assert run._settings.resume_fname == os.path.join(
        run._settings.wandb_dir, "wandb-resume.json"
    )


def test_wandb_dir_run(mock_run):
    run = mock_run()
    assert os.path.abspath(run._settings.wandb_dir) == os.path.abspath(
        os.path.join(run._settings.wandb_dir)
    )


def test_console_run(mock_run):
    run = mock_run(settings={"console": "auto", "mode": "offline"})
    assert run._settings.console == "wrap"


def test_console():
    test_settings = Settings(console="off")
    assert test_settings.console == "off"
    test_settings.console = "redirect"
    assert test_settings.console == "redirect"
    test_settings.console = "wrap"
    assert test_settings.console == "wrap"


def test_code_saving_save_code_env_false(mock_run):
    settings = Settings()
    settings.save_code = None
    with mock.patch.dict("os.environ", WANDB_SAVE_CODE="false"):
        settings.update_from_system_environment()
        run = mock_run(settings=settings)
        assert run._settings.save_code is False


def test_code_saving_disable_code(mock_run):
    settings = Settings()
    settings.save_code = None
    with mock.patch.dict("os.environ", WANDB_DISABLE_CODE="true"):
        settings.update_from_system_environment()
        run = mock_run(settings=settings)
        assert run.settings.save_code is False


def test_setup_offline():
    login_settings = Settings()
    login_settings.mode = "offline"
    assert wandb.setup(settings=login_settings)._get_entity() is None


def test_mutual_exclusion_of_branching_args():
    run_id = "test"
    with pytest.raises(ValueError):
        Settings(run_id=run_id, resume_from=f"{run_id}?_step=10", resume="allow")


def test_root_dir_pathlib_path():
    settings = Settings(root_dir=pathlib.Path("foo"))
    assert settings.root_dir == "foo"


@pytest.mark.parametrize(
    "setting",
    (
        "fork_from",
        "resume_from",
    ),
)
def test_rewind(setting):
    settings = Settings()
    setattr(settings, setting, "train-2025-01-12_05-02-41-823103-39?_step=10000")

    assert getattr(settings, setting) == RunMoment(
        run="train-2025-01-12_05-02-41-823103-39",
        metric="_step",
        value=10000,
    )
    proto = settings.to_proto()
    assert getattr(proto, setting).run == "train-2025-01-12_05-02-41-823103-39"
    assert getattr(proto, setting).metric == "_step"
    assert getattr(proto, setting).value == 10000


def test_computed_settings_included_in_model_dump():
    settings = Settings(mode="offline")
    assert settings.model_dump()["_offline"] is True


@pytest.mark.skipif(
    platform.system() != "Windows",
    reason="Drive letters are only relevant on Windows",
)
@pytest.mark.parametrize(
    "root_dir,expected_result",
    [
        ("C:\\other", lambda x: x is not None),
        ("D:\\other", lambda x: x is None),
    ],
)
def test_program_relpath_windows(root_dir, expected_result):
    with tempfile.TemporaryDirectory() as temp_dir:
        test_file_path = os.path.join(temp_dir, "test_file.py")
        with open(test_file_path, "w") as f:
            f.write("# Test file for program_relpath testing")
        result = Settings._get_program_relpath(test_file_path, root_dir)
        assert expected_result(result)


@pytest.mark.parametrize("restricted_chars", [":", ";", ",", "#", "?", "/", "'"])
def test_run_id_validation(restricted_chars):
    with pytest.raises(UsageError):
        Settings(run_id=f"test{restricted_chars}")
