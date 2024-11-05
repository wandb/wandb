import os
import subprocess
import sys
import tempfile

import pytest
import wandb
from wandb import Settings
from wandb.errors import UsageError

if sys.version_info >= (3, 8):
    pass
else:
    pass


@pytest.mark.skip(reason="Current behavior is to silently ignore unexpected arguments")
def test_unexpected_arguments():
    with pytest.raises(TypeError):
        Settings(lol=False)


def test_mapping_interface():
    settings = Settings()
    for _ in settings:
        pass


def test_is_local():
    s = Settings(base_url="https://api.wandb.ai")
    assert s.is_local is False


def test_extra_fields():
    with pytest.raises(ValueError):
        Settings(lol=True)


def test_invalid_field_type():
    with pytest.raises(ValueError):
        Settings(api_key=271828)  # must be a string


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


def test_offline(test_settings):
    test_settings = test_settings()
    assert test_settings._offline is False
    test_settings.mode = "offline"
    assert test_settings._offline is True
    test_settings.mode = "dryrun"
    assert test_settings._offline is True


def test_silent(test_settings):
    s = test_settings()
    s.from_env_vars({"WANDB_SILENT": "true"})
    assert s.silent is True


# def test_show_info(test_settings):
#     test_settings = test_settings()
#     test_settings.update({"show_info": True}, source=Source.BASE)
#     assert test_settings.show_info is True

#     test_settings.update({"show_info": False}, source=Source.BASE)
#     assert test_settings.show_info is False


# def test_show_warnings(test_settings):
#     test_settings = test_settings()
#     test_settings.update({"show_warnings": "true"}, source=Source.SETTINGS)
#     assert test_settings.show_warnings is True

#     test_settings.update({"show_warnings": "false"}, source=Source.SETTINGS)
#     assert test_settings.show_warnings is False


# def test_show_errors(test_settings):
#     test_settings = test_settings()
#     test_settings.update({"show_errors": True}, source=Source.SETTINGS)
#     assert test_settings.show_errors is True

#     test_settings.update({"show_errors": False}, source=Source.SETTINGS)
#     assert test_settings.show_errors is False


# def test_noop(test_settings):
#     test_settings = test_settings()
#     test_settings.update({"mode": "disabled"}, source=Source.BASE)
#     assert test_settings._noop is True


# def test_attrib_get():
#     s = Settings()
#     assert s.base_url == "https://api.wandb.ai"


# def test_attrib_set_not_allowed():
#     s = Settings()
#     with pytest.raises(TypeError):
#         s.base_url = "new"


# def test_attrib_get_bad():
#     s = Settings()
#     with pytest.raises(AttributeError):
#         s.missing  # noqa: B018


# def test_update_override():
#     s = Settings()
#     s.update(dict(base_url="https://something2.local"), source=Source.OVERRIDE)
#     assert s.base_url == "https://something2.local"


# def test_update_priorities():
#     s = Settings()
#     # USER has higher priority than ORG (and both are higher priority than BASE)
#     s.update(dict(base_url="https://foo.local"), source=Source.USER)
#     assert s.base_url == "https://foo.local"
#     s.update(dict(base_url="https://bar.local"), source=Source.ORG)
#     assert s.base_url == "https://foo.local"


# def test_update_priorities_order():
#     s = Settings()
#     # USER has higher priority than ORG (and both are higher priority than BASE)
#     s.update(dict(base_url="https://bar.local"), source=Source.ORG)
#     assert s.base_url == "https://bar.local"
#     s.update(dict(base_url="https://foo.local"), source=Source.USER)
#     assert s.base_url == "https://foo.local"


# def test_update_missing_attrib():
#     s = Settings()
#     with pytest.raises(KeyError):
#         s.update(dict(missing="nope"), source=Source.OVERRIDE)


# def test_update_kwargs():
#     s = Settings()
#     s.update(base_url="https://something.local")
#     assert s.base_url == "https://something.local"


# def test_update_both():
#     s = Settings()
#     s.update(dict(base_url="https://something.local"), project="nothing")
#     assert s.base_url == "https://something.local"
#     assert s.project == "nothing"


# def test_ignore_globs():
#     s = Settings()
#     assert s.ignore_globs == ()


# def test_ignore_globs_explicit():
#     s = Settings(ignore_globs=["foo"])
#     assert s.ignore_globs == ("foo",)


# def test_ignore_globs_env():
#     s = Settings()
#     s._apply_env_vars({"WANDB_IGNORE_GLOBS": "foo"})
#     assert s.ignore_globs == ("foo",)

#     s = Settings()
#     s._apply_env_vars({"WANDB_IGNORE_GLOBS": "foo,bar"})
#     assert s.ignore_globs == (
#         "foo",
#         "bar",
#     )


# def test_token_file_env():
#     s = Settings()
#     s._apply_env_vars({"WANDB_IDENTITY_TOKEN_FILE": "jwt.txt"})
#     assert s.identity_token_file == ("jwt.txt")


# def test_credentials_file_env():
#     s = Settings()
#     assert s.credentials_file == str(DEFAULT_WANDB_CREDENTIALS_FILE)

#     s = Settings()
#     s._apply_env_vars({"WANDB_CREDENTIALS_FILE": "/tmp/credentials.json"})
#     assert s.credentials_file == "/tmp/credentials.json"


# def test_quiet():
#     s = Settings()
#     assert s.quiet is None
#     s = Settings(quiet=True)
#     assert s.quiet
#     s = Settings()
#     s._apply_env_vars({"WANDB_QUIET": "false"})
#     assert not s.quiet


# @pytest.mark.skip(reason="I need to make my mock work properly with new settings")
# def test_ignore_globs_settings(local_settings):
#     with open(os.path.join(os.getcwd(), ".config", "wandb", "settings"), "w") as f:
#         f.write(
#             """[default]
# ignore_globs=foo,bar"""
#         )
#     s = Settings(_files=True)
#     assert s.ignore_globs == (
#         "foo",
#         "bar",
#     )


# def test_copy():
#     s = Settings()
#     s.update(base_url="https://changed.local")
#     s2 = copy.copy(s)
#     assert s2.base_url == "https://changed.local"
#     s.update(base_url="https://not.changed.local")
#     assert s.base_url == "https://not.changed.local"
#     assert s2.base_url == "https://changed.local"


# def test_update_linked_properties():
#     s = Settings()
#     # sync_dir depends, among other things, on run_mode
#     assert s.mode == "online"
#     assert s.run_mode == "run"
#     assert ("offline-run" not in s.sync_dir) and ("run" in s.sync_dir)
#     s.update(mode="offline")
#     assert s.mode == "offline"
#     assert s.run_mode == "offline-run"
#     assert "offline-run" in s.sync_dir


# def test_copy_update_linked_properties():
#     s = Settings()
#     assert s.mode == "online"
#     assert s.run_mode == "run"
#     assert ("offline-run" not in s.sync_dir) and ("run" in s.sync_dir)

#     s2 = copy.copy(s)
#     assert s2.mode == "online"
#     assert s2.run_mode == "run"
#     assert ("offline-run" not in s2.sync_dir) and ("run" in s2.sync_dir)

#     s.update(mode="offline")
#     assert s.mode == "offline"
#     assert s.run_mode == "offline-run"
#     assert "offline-run" in s.sync_dir
#     assert s2.mode == "online"
#     assert s2.run_mode == "run"
#     assert ("offline-run" not in s2.sync_dir) and ("run" in s2.sync_dir)

#     s2.update(mode="offline")
#     assert s2.mode == "offline"
#     assert s2.run_mode == "offline-run"
#     assert "offline-run" in s2.sync_dir


# def test_invalid_dict():
#     s = Settings()
#     with pytest.raises(KeyError):
#         s.update(dict(invalid="new"))


# def test_invalid_kwargs():
#     s = Settings()
#     with pytest.raises(KeyError):
#         s.update(invalid="new")


# def test_invalid_both():
#     s = Settings()
#     with pytest.raises(KeyError):
#         s.update(dict(project="ok"), invalid="new")
#     assert s.project != "ok"
#     with pytest.raises(KeyError):
#         s.update(dict(wrong="bad", entity="nope"), project="okbutnotset")
#     assert s.entity != "nope"
#     assert s.project != "okbutnotset"


# def test_freeze():
#     s = Settings()
#     s.update(project="goodprojo")
#     assert s.project == "goodprojo"
#     s.freeze()
#     assert s.is_frozen()
#     with pytest.raises(TypeError):
#         s.update(project="badprojo")
#     assert s.project == "goodprojo"
#     with pytest.raises(TypeError):
#         s.update(project="badprojo2")
#     c = copy.copy(s)
#     assert c.project == "goodprojo"
#     c.update(project="changed")
#     assert c.project == "changed"
#     assert s.project == "goodprojo"


# def test_bad_choice():
#     s = Settings()
#     with pytest.raises(TypeError):
#         s.mode = "goodprojo"
#     with pytest.raises(UsageError):
#         s.update(mode="badmode")


# def test_priority_update_greater_source():
#     s = Settings()
#     # for a non-policy setting, greater source (PROJECT) has higher priority
#     s.update(project="pizza", source=Source.ENTITY)
#     assert s.project == "pizza"
#     s.update(project="pizza2", source=Source.PROJECT)
#     assert s.project == "pizza2"


# def test_priority_update_smaller_source():
#     s = Settings()
#     s.update(project="pizza", source=Source.PROJECT)
#     assert s.project == "pizza"
#     s.update(project="pizza2", source=Source.ENTITY)
#     # for a non-policy setting, greater source (PROJECT) has higher priority
#     assert s.project == "pizza"


# def test_priority_update_policy_greater_source():
#     s = Settings()
#     # for a policy setting, greater source (PROJECT) has lower priority
#     s.update(summary_warnings=42, source=Source.PROJECT)
#     assert s.summary_warnings == 42
#     s.update(summary_warnings=43, source=Source.ENTITY)
#     assert s.summary_warnings == 43


# def test_priority_update_policy_smaller_source():
#     s = Settings()
#     # for a policy setting, greater source (PROJECT) has lower priority
#     s.update(summary_warnings=42, source=Source.ENTITY)
#     assert s.summary_warnings == 42
#     s.update(summary_warnings=43, source=Source.PROJECT)
#     assert s.summary_warnings == 42


# @pytest.mark.parametrize(
#     "url",
#     [
#         "https://api.wandb.ai",
#         "https://wandb.ai.other.crazy.domain.com",
#         "https://127.0.0.1",
#         "https://localhost",
#         "https://192.168.31.1:8080",
#         "https://myhost:8888",  # fixme: should this be allowed?
#     ],
# )
# def test_validate_base_url(url):
#     s = Settings(base_url=url)
#     assert s.base_url == url


# @pytest.mark.parametrize(
#     "url, error",
#     [
#         (
#             "https://wandb.ai",
#             "is not a valid server address, did you mean https://api.wandb.ai?",
#         ),
#         (
#             "https://app.wandb.ai",
#             "is not a valid server address, did you mean https://api.wandb.ai?",
#         ),
#         ("http://api.wandb.ai", "http is not secure, please use https://api.wandb.ai"),
#         ("http://host\t.ai", "URL cannot contain unsafe characters"),
#         ("http://host\n.ai", "URL cannot contain unsafe characters"),
#         ("http://host\r.ai", "URL cannot contain unsafe characters"),
#         ("ftp://host.ai", "URL must start with `http(s)://`"),
#         (
#             "gibberish",
#             "gibberish is not a valid server address",
#         ),
#         ("LOL" * 100, "hostname is invalid"),
#     ],
# )
# def test_validate_invalid_base_url(capsys, url, error):
#     s = Settings()
#     with pytest.raises(UsageError):
#         s.update(base_url=url)
#         captured = capsys.readouterr().err
#         assert error in captured


# @pytest.mark.parametrize(
#     "url, processed_url",
#     [
#         ("https://host.com", "https://host.com"),
#         ("https://host.com/", "https://host.com"),
#         ("https://host.com///", "https://host.com"),
#     ],
# )
# def test_preprocess_base_url(url, processed_url):
#     s = Settings()
#     s.update(base_url=url)
#     assert s.base_url == processed_url


# @pytest.mark.parametrize(
#     "setting",
#     [
#         "_disable_meta",
#         "_disable_stats",
#         "_disable_viewer",
#         "disable_code",
#         "disable_git",
#         "disabled",
#         "force",
#         "label_disable",
#         "launch",
#         "quiet",
#         "reinit",
#         "relogin",
#         "sagemaker_disable",
#         "save_code",
#         "show_colors",
#         "show_emoji",
#         "show_errors",
#         "show_info",
#         "show_warnings",
#         "silent",
#         "strict",
#     ],
# )
# def test_preprocess_bool_settings(setting: str):
#     with mock.patch.dict(os.environ, {"WANDB_" + setting.upper(): "true"}):
#         s = Settings()
#         s._apply_env_vars(environ=os.environ)
#         assert s[setting] is True


# @pytest.mark.parametrize(
#     "setting, value",
#     [
#         ("_stats_open_metrics_endpoints", '{"DCGM":"http://localhvost"}'),
#         (
#             "_stats_open_metrics_filters",
#             '{"DCGM_FI_DEV_POWER_USAGE": {"pod": "dcgm-*"}}',
#         ),
#     ],
# )
# def test_preprocess_dict_settings(setting: str, value: str):
#     with mock.patch.dict(os.environ, {"WANDB_" + setting.upper(): value}):
#         s = Settings()
#         s._apply_env_vars(environ=os.environ)
#         assert s[setting] == json.loads(value)


# def test_redact():
#     # normal redact case
#     redacted = wandb_settings._redact_dict({"this": 2, "that": 9, "api_key": "secret"})
#     assert redacted == {"this": 2, "that": 9, "api_key": "***REDACTED***"}

#     # two redacted keys with options passed
#     redacted = wandb_settings._redact_dict(
#         {"ok": "keep", "unsafe": 9, "bad": "secret"},
#         unsafe_keys={"unsafe", "bad"},
#         redact_str="OMIT",
#     )
#     assert redacted == {"ok": "keep", "unsafe": "OMIT", "bad": "OMIT"}

#     # all keys fine
#     redacted = wandb_settings._redact_dict({"all": "keep", "good": 9, "keys": "fine"})
#     assert redacted == {"all": "keep", "good": 9, "keys": "fine"}

#     # empty case
#     redacted = wandb_settings._redact_dict({})
#     assert redacted == {}

#     # all keys redacted
#     redacted = wandb_settings._redact_dict({"api_key": "secret"})
#     assert redacted == {"api_key": "***REDACTED***"}


# def test_strict():
#     settings = Settings(strict=True)
#     assert settings.strict is True

#     settings = Settings(strict=False)
#     assert not settings.strict


# def test_validate_console_anonymous():
#     s = Settings()
#     with pytest.raises(UsageError):
#         s.update(console="lol")
#     with pytest.raises(UsageError):
#         s.update(anonymous="lol")


# def test_wandb_dir(test_settings):
#     test_settings = test_settings()
#     assert os.path.abspath(test_settings.wandb_dir) == os.path.abspath("wandb")


# def test_resume_fname(test_settings):
#     test_settings = test_settings()
#     assert test_settings.resume_fname == os.path.abspath(
#         os.path.join(".", "wandb", "wandb-resume.json")
#     )


# @pytest.mark.skip(reason="CircleCI still lets you write to root_dir")
# def test_non_writable_root_dir(capsys):
#     with CliRunner().isolated_filesystem():
#         root_dir = os.getcwd()
#         s = Settings()
#         s.update(root_dir=root_dir)
#         # make root_dir non-writable
#         os.chmod(root_dir, 0o444)
#         wandb_dir = s.wandb_dir
#         assert wandb_dir != "/wandb"
#         _, err = capsys.readouterr()
#         assert "wasn't writable, using system temp directory" in err


# def test_log_user(test_settings):
#     test_settings = test_settings({"run_id": "test"})
#     _, run_dir, log_dir, fname = os.path.abspath(
#         os.path.realpath(test_settings.log_user)
#     ).rsplit(os.path.sep, 3)
#     _, _, run_id = run_dir.split("-")
#     assert run_id == test_settings.run_id
#     assert log_dir == "logs"
#     assert fname == "debug.log"


# def test_log_internal(test_settings):
#     test_settings = test_settings({"run_id": "test"})
#     _, run_dir, log_dir, fname = os.path.abspath(
#         os.path.realpath(test_settings.log_internal)
#     ).rsplit(os.path.sep, 3)
#     _, _, run_id = run_dir.split("-")
#     assert run_id == test_settings.run_id
#     assert log_dir == "logs"
#     assert fname == "debug-internal.log"


# # --------------------------
# # test static settings
# # --------------------------


# def test_settings_static():
#     from wandb.sdk.internal.settings_static import SettingsStatic

#     static_settings = SettingsStatic(Settings().to_proto())
#     assert "base_url" in static_settings
#     assert static_settings.base_url == "https://api.wandb.ai"


# # --------------------------
# # test run settings
# # --------------------------


# def test_silent_run(mock_run, test_settings):
#     test_settings = test_settings()
#     test_settings.update({"silent": "true"}, source=Source.SETTINGS)
#     assert test_settings.silent is True
#     run = mock_run(settings=test_settings)
#     assert run._settings.silent is True


# def test_strict_run(mock_run, test_settings):
#     test_settings = test_settings()
#     test_settings.update({"strict": "true"}, source=Source.SETTINGS)
#     assert test_settings.strict is True
#     run = mock_run(settings=test_settings)
#     assert run._settings.strict is True


# def test_show_info_run(mock_run):
#     run = mock_run()
#     assert run._settings.show_info is True


# def test_show_info_false_run(mock_run, test_settings):
#     test_settings = test_settings()
#     test_settings.update({"show_info": "false"}, source=Source.SETTINGS)
#     run = mock_run(settings=test_settings)
#     assert run._settings.show_info is False


# def test_show_warnings_run(mock_run, test_settings):
#     test_settings = test_settings()
#     test_settings.update({"show_warnings": "true"}, source=Source.SETTINGS)
#     run = mock_run(settings=test_settings)
#     assert run._settings.show_warnings is True


# def test_show_warnings_false_run(mock_run, test_settings):
#     test_settings = test_settings()
#     test_settings.update({"show_warnings": "false"}, source=Source.SETTINGS)
#     run = mock_run(settings=test_settings)
#     assert run._settings.show_warnings is False


# def test_show_errors_run(mock_run, test_settings):
#     test_settings = test_settings()
#     test_settings.update({"show_errors": True}, source=Source.SETTINGS)
#     run = mock_run(settings=test_settings)
#     assert run._settings.show_errors is True


# def test_show_errors_false_run(mock_run, test_settings):
#     test_settings = test_settings()
#     test_settings.update({"show_errors": False}, source=Source.SETTINGS)
#     run = mock_run(settings=test_settings)
#     assert run._settings.show_errors is False


# def test_not_jupyter(mock_run):
#     run = mock_run()
#     assert run._settings._jupyter is False


# def test_resume_fname_run(mock_run):
#     run = mock_run()
#     assert run._settings.resume_fname == os.path.join(
#         run._settings.root_dir, "wandb", "wandb-resume.json"
#     )


# def test_wandb_dir_run(mock_run):
#     run = mock_run()
#     assert os.path.abspath(run._settings.wandb_dir) == os.path.abspath(
#         os.path.join(run._settings.root_dir, "wandb")
#     )


# def test_console_run(mock_run):
#     run = mock_run(settings={"console": "auto", "mode": "offline"})
#     assert run._settings.console == "wrap"


# def test_console(test_settings):
#     test_settings = test_settings()
#     assert test_settings.console == "off"
#     test_settings.update({"console": "redirect"}, source=Source.BASE)
#     assert test_settings.console == "redirect"
#     test_settings.update({"console": "wrap"}, source=Source.BASE)
#     assert test_settings.console == "wrap"


# def test_code_saving_save_code_env_false(mock_run, test_settings):
#     settings = test_settings()
#     settings.update({"save_code": None}, source=Source.BASE)
#     with mock.patch.dict("os.environ", WANDB_SAVE_CODE="false"):
#         settings._infer_settings_from_environment()
#         run = mock_run(settings=settings)
#         assert run._settings.save_code is False


# def test_code_saving_disable_code(mock_run, test_settings):
#     settings = test_settings()
#     settings.update({"save_code": None}, source=Source.BASE)
#     with mock.patch.dict("os.environ", WANDB_DISABLE_CODE="true"):
#         settings._infer_settings_from_environment()
#         run = mock_run(settings=settings)
#         assert run.settings.save_code is False


# def test_setup_offline(test_settings):
#     # this is to increase coverage
#     login_settings = test_settings().copy()
#     login_settings.update(mode="offline")
#     assert wandb.setup(settings=login_settings)._instance._get_entity() is None
#     assert wandb.setup(settings=login_settings)._instance._load_viewer() is None


# def test_disable_machine_info(test_settings):
#     settings = test_settings()
#     attrs = (
#         "_disable_stats",
#         "_disable_meta",
#         "disable_code",
#         "disable_git",
#         "disable_job_creation",
#     )
#     for attr in attrs:
#         assert not getattr(settings, attr)
#     settings.update({"_disable_machine_info": True}, source=Source.BASE)
#     for attr in attrs:
#         assert getattr(settings, attr) is True
#     settings.update({"_disable_machine_info": False}, source=Source.BASE)
#     for attr in attrs:
#         assert getattr(settings, attr) is False


# @pytest.mark.skip(reason="causes other tests that depend on capsys to fail")
# def test_silent_env_run(mock_run, test_settings):
#     settings = test_settings()
#     with mock.patch.dict("os.environ", WANDB_SILENT="true"):
#         settings._apply_env_vars(os.environ)
#         run = mock_run(settings=settings)
#         assert run._settings.silent is True


# def test_is_instance_recursive():
#     # Test with simple types
#     assert is_instance_recursive(42, int)
#     assert not is_instance_recursive(42, str)
#     assert is_instance_recursive("hello", str)
#     assert not is_instance_recursive("hello", int)

#     # Test with Any type
#     assert is_instance_recursive(42, Any)
#     assert is_instance_recursive("hello", Any)
#     assert is_instance_recursive([1, 2, 3], Any)
#     assert is_instance_recursive({"a": 1, "b": 2}, Any)

#     # Test with Union
#     assert is_instance_recursive(42, Union[int, str])
#     assert is_instance_recursive("hello", Union[int, str])
#     assert not is_instance_recursive([1, 2, 3], Union[int, str])

#     # Test with Mapping
#     assert is_instance_recursive({"a": 1, "b": 2}, Dict[str, int])
#     assert not is_instance_recursive({"a": 1, "b": "2"}, Dict[str, int])
#     assert not is_instance_recursive([("a", 1), ("b", 2)], Dict[str, int])

#     # Test with Sequence
#     assert is_instance_recursive([1, 2, 3], List[int])
#     assert not is_instance_recursive([1, 2, "3"], List[int])
#     assert not is_instance_recursive("123", List[int])
#     assert is_instance_recursive([(1, 2), (3, 4)], List[Tuple[int, int]])
#     assert not is_instance_recursive([(1, 2), (3, "4")], List[Tuple[int, int]])

#     # Test with fixed-length Sequence
#     assert is_instance_recursive([1, "a", 3.5], Tuple[int, str, float])
#     assert not is_instance_recursive([1, "a", "3.5"], Tuple[int, str, float])
#     assert not is_instance_recursive([1, "a"], Tuple[int, str, float])

#     # Test with Tuple of variable length
#     assert is_instance_recursive((1, 2, 3), Tuple[int, ...])
#     assert not is_instance_recursive((1, 2, "a"), Tuple[int, ...])
#     assert is_instance_recursive((1, 2, "a"), Tuple[Union[int, str], ...])

#     # Test with Set
#     assert is_instance_recursive({1, 2, 3}, Set[int])
#     assert not is_instance_recursive({1, 2, "3"}, Set[int])
#     assert not is_instance_recursive([1, 2, 3], Set[int])

#     # Test with nested types
#     assert is_instance_recursive({"a": [1, 2], "b": [3, 4]}, Dict[str, List[int]])
#     assert not is_instance_recursive({"a": [1, 2], "b": [3, "4"]}, Dict[str, List[int]])


# def test_is_instance_recursive_mapping_and_sequence():
#     # Test with Mapping
#     assert is_instance_recursive({"a": 1, "b": 2}, Mapping[str, int])
#     assert not is_instance_recursive({"a": 1, "b": "2"}, Mapping[str, int])
#     assert not is_instance_recursive([("a", 1), ("b", 2)], Mapping[str, int])

#     # Test with Sequence
#     assert is_instance_recursive([1, 2, 3], Sequence[int])
#     assert not is_instance_recursive([1, 2, "3"], Sequence[int])
#     assert not is_instance_recursive("123", Sequence[int])
#     assert is_instance_recursive([(1, 2), (3, 4)], Sequence[Tuple[int, int]])
#     assert not is_instance_recursive([(1, 2), (3, "4")], Sequence[Tuple[int, int]])

#     # Test with nested types and Mapping
#     assert is_instance_recursive(
#         {"a": [1, 2], "b": [3, 4]}, Mapping[str, Sequence[int]]
#     )
#     assert not is_instance_recursive(
#         {"a": [1, 2], "b": [3, "4"]}, Mapping[str, Sequence[int]]
#     )

#     # Test with nested types and Sequence
#     assert is_instance_recursive(
#         [{"a": 1, "b": 2}, {"c": 3, "d": 4}], Sequence[Mapping[str, int]]
#     )
#     assert not is_instance_recursive(
#         [{"a": 1, "b": 2}, {"c": 3, "d": "4"}], Sequence[Mapping[str, int]]
#     )


# def test_is_instance_recursive_custom_types():
#     class Custom:
#         pass

#     class CustomSubclass(Custom):
#         pass

#     assert is_instance_recursive(Custom(), Custom)
#     assert is_instance_recursive(CustomSubclass(), Custom)
#     assert not is_instance_recursive(Custom(), CustomSubclass)
#     assert is_instance_recursive(CustomSubclass(), CustomSubclass)

#     # container types
#     assert is_instance_recursive([Custom()], List[Custom])
#     assert is_instance_recursive([CustomSubclass()], List[Custom])
#     assert is_instance_recursive(
#         {"a": Custom(), "b": CustomSubclass()}, Mapping[str, Custom]
#     )
