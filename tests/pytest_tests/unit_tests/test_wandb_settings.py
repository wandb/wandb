import copy
import inspect
import json
import os
import subprocess
import sys
import tempfile
from typing import Optional
from unittest import mock

import pytest
import wandb
from click.testing import CliRunner
from wandb.errors import UsageError
from wandb.sdk import wandb_login, wandb_settings
from wandb.sdk.lib._settings_toposort_generate import _get_modification_order

if sys.version_info >= (3, 8):
    from typing import get_type_hints
elif sys.version_info >= (3, 7):
    from typing_extensions import get_type_hints
else:

    def get_type_hints(obj):
        return obj.__annotations__


Property = wandb_settings.Property
Settings = wandb_settings.Settings
Source = wandb_settings.Source


def test_multiproc_strict_bad(test_settings):
    with pytest.raises(ValueError):
        test_settings(dict(strict="bad"))


def test_str_as_bool():
    for val in ("y", "yes", "t", "true", "on", "1", "True", "TRUE"):
        assert wandb_settings._str_as_bool(val)
    for val in ("n", "no", "f", "false", "off", "0", "False", "FALSE"):
        assert not wandb_settings._str_as_bool(val)
    with pytest.raises(UsageError):
        wandb_settings._str_as_bool("rubbish")


# ------------------------------------
# test Property class
# ------------------------------------


def test_property_init():
    p = Property(name="foo", value=1)
    assert p.name == "foo"
    assert p.value == 1
    assert p._source == Source.BASE
    assert not p._is_policy


def test_property_preprocess_and_validate():
    p = Property(
        name="foo",
        value=1,
        preprocessor=lambda x: str(x),
        validator=lambda x: isinstance(x, str),
    )
    assert p.name == "foo"
    assert p.value == "1"
    assert p._source == Source.BASE
    assert not p._is_policy


def test_property_preprocess_validate_hook():
    p = Property(
        name="foo",
        value="2",
        preprocessor=lambda x: int(x),
        validator=lambda x: isinstance(x, int),
        hook=lambda x: x**2,
        source=Source.OVERRIDE,
    )
    assert p._source == Source.OVERRIDE
    assert p.value == 4
    assert not p._is_policy


def test_property_auto_hook():
    p = Property(
        name="foo",
        value=None,
        hook=lambda x: "WANDB",
        auto_hook=True,
    )
    assert p.value == "WANDB"

    p = Property(
        name="foo",
        value=None,
        hook=lambda x: "WANDB",
        auto_hook=False,
    )
    assert p.value is None


# fixme:
@pytest.mark.skip(
    reason="For now, we don't enforce validation on properties that are not in __strict_validate_settings"
)
def test_property_multiple_validators():
    def meaning_of_life(x):
        return x == 42

    p = Property(
        name="foo",
        value=42,
        validator=[lambda x: isinstance(x, int), meaning_of_life],
    )
    assert p.value == 42
    with pytest.raises(ValueError):
        p.update(value=43)


# fixme: remove this once full validation is restored
def test_property_strict_validation(capsys):
    attributes = inspect.getmembers(Property, lambda a: not (inspect.isroutine(a)))
    strict_validate_settings = [
        a for a in attributes if a[0] == "_Property__strict_validate_settings"
    ][0][1]
    for name in strict_validate_settings:
        p = Property(name=name, validator=lambda x: isinstance(x, int))
        with pytest.raises(ValueError):
            p.update(value="rubbish")

    p = Property(name="api_key", validator=lambda x: isinstance(x, str))
    p.update(value=31415926)
    captured = capsys.readouterr().err
    msg = "Invalid value for property api_key: 31415926"
    assert msg in captured


def test_settings_validator_method_names():
    # Settings validator methods should be named `_validate_<setting_name>`
    s = wandb.Settings()
    prefix = "_validate_"
    symbols = set(dir(s))
    validator_methods = tuple(m for m in symbols if m.startswith(prefix))

    assert all(tuple(m.split(prefix)[1] in symbols for m in validator_methods))


def test_settings_modification_order():
    # Settings should be modified in the order that respects the dependencies
    # between settings manifested in validator methods and runtime hooks.
    s = wandb.Settings()
    modification_order = s._Settings__modification_order
    # todo: uncomment once api_key validation is restored:
    # assert (
    #     modification_order.index("base_url")
    #     < modification_order.index("is_local")
    #     < modification_order.index("api_key")
    # )
    assert modification_order.index("_network_buffer") < modification_order.index(
        "_flow_control_custom"
    )


def test_settings_modification_order_up_to_date():
    # Assert that the modification order is up-to-date with the generated code
    s = wandb.Settings()
    props = tuple(get_type_hints(Settings).keys())
    modification_order = s._Settings__modification_order

    _settings_literal_list, _settings_topologically_sorted = _get_modification_order(s)

    assert props == _settings_literal_list
    assert modification_order == _settings_topologically_sorted


def test_settings_detect_cycle_in_dependencies():
    # Settings modification order generator
    # should detect cycles in dependencies between settings

    def _mock_default_props(self):
        props = dict(
            api_key={"validator": self._validate_api_key},
            base_url={
                "hook": lambda _: "https://localhost"
                if self.is_local
                else "https://api.wandb.ai",
                "auto_hook": True,
            },
            is_local={
                "hook": lambda _: self.base_url is not None,
                "auto_hook": True,
            },
        )
        return props

    with mock.patch.object(Settings, "_default_props", _mock_default_props):
        with pytest.raises(wandb.UsageError):
            _get_modification_order(wandb.Settings())


def test_property_update():
    p = Property(name="foo", value=1)
    p.update(value=2)
    assert p.value == 2


def test_property_update_sources():
    p = Property(name="foo", value=1, source=Source.ORG)
    assert p.value == 1
    # smaller source => lower priority
    # lower priority:
    p.update(value=2, source=Source.BASE)
    assert p.value == 1
    # higher priority:
    p.update(value=3, source=Source.USER)
    assert p.value == 3


def test_property_update_policy_sources():
    p = Property(name="foo", value=1, is_policy=True, source=Source.ORG)
    assert p.value == 1
    # smaller source => higher priority
    # higher priority:
    p.update(value=2, source=Source.BASE)
    assert p.value == 2
    # higher priority:
    p.update(value=3, source=Source.USER)
    assert p.value == 2


def test_property_set_value_directly_forbidden():
    p = Property(name="foo", value=1)
    with pytest.raises(AttributeError):
        p.value = 2


def test_property_update_frozen_forbidden():
    p = Property(name="foo", value=1, frozen=True)
    with pytest.raises(TypeError):
        p.update(value=2)


# test str and repr methods for Property class


def test_property_str():
    p = Property(name="foo", value="1")
    assert str(p) == "'1'"
    p = Property(name="foo", value=1)
    assert str(p) == "1"


def test_property_repr():
    p = Property(name="foo", value=2, hook=lambda x: x**2)
    assert repr(p) == "<Property foo: value=4 _value=2 source=1 is_policy=False>"


# ------------------------------------
# test Settings class
# ------------------------------------


def test_start_run():
    s = Settings()
    s._set_run_start_time()
    assert s._Settings_start_time is not None
    assert s._Settings_start_datetime is not None


# fixme:
@pytest.mark.skip(reason="For now, we don't raise an error and simply ignore it")
def test_unexpected_arguments():
    with pytest.raises(TypeError):
        Settings(lol=False)


def test_mapping_interface():
    s = Settings()
    for setting in s:
        assert setting in s


def test_is_local():
    s = Settings(base_url=None)
    assert s.is_local is False


def test_default_props_match_class_attributes():
    # make sure that the default properties match the class attributes
    s = Settings()
    class_attributes = list(get_type_hints(Settings).keys())
    default_props = list(s._default_props().keys())
    assert set(default_props) - set(class_attributes) == set()


# fixme: remove this once full validation is restored
def test_settings_strict_validation(capsys):
    s = Settings(api_key=271828, lol=True)
    assert s.api_key == 271828
    with pytest.raises(AttributeError):
        s.lol  # noqa: B018
    captured = capsys.readouterr().err
    msgs = (
        "Ignoring unexpected arguments: ['lol']",
        "Invalid value for property api_key: 271828",
    )
    for msg in msgs:
        assert msg in captured


def test_static_settings_json_dump():
    s = Settings()
    static_settings = s.make_static()
    assert json.dumps(static_settings)


# fixme: remove this once full validation is restored
def test_no_repeat_warnings(capsys):
    s = Settings(api_key=234)
    assert s.api_key == 234
    s.update(api_key=234)
    captured = capsys.readouterr().err
    msg = "Invalid value for property api_key: 234"
    assert captured.count(msg) == 1


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
        )
    s = wandb.Settings(
        api_key="local-87eLxjoRhY6u2ofg63NAJo7rVYHZo4NGACOvpSsF",
        base_url="https://api.wandb.test",
    )

    # ensure that base_url is copied first without causing an error in api_key validation
    s.copy()

    # ensure that base_url is applied first without causing an error in api_key validation
    wandb.Settings()._apply_settings(s)


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
    test_settings.update({"disabled": True}, source=Source.BASE)
    assert test_settings._offline is True
    test_settings.update({"disabled": None}, source=Source.BASE)
    test_settings.update({"mode": "dryrun"}, source=Source.BASE)
    assert test_settings._offline is True
    test_settings.update({"mode": "offline"}, source=Source.BASE)
    assert test_settings._offline is True


def test_silent(test_settings):
    test_settings = test_settings()
    test_settings.update({"silent": "true"}, source=Source.BASE)
    assert test_settings.silent is True


def test_show_info(test_settings):
    test_settings = test_settings()
    test_settings.update({"show_info": True}, source=Source.BASE)
    assert test_settings.show_info is True

    test_settings.update({"show_info": False}, source=Source.BASE)
    assert test_settings.show_info is False


def test_show_warnings(test_settings):
    test_settings = test_settings()
    test_settings.update({"show_warnings": "true"}, source=Source.SETTINGS)
    assert test_settings.show_warnings is True

    test_settings.update({"show_warnings": "false"}, source=Source.SETTINGS)
    assert test_settings.show_warnings is False


def test_show_errors(test_settings):
    test_settings = test_settings()
    test_settings.update({"show_errors": True}, source=Source.SETTINGS)
    assert test_settings.show_errors is True

    test_settings.update({"show_errors": False}, source=Source.SETTINGS)
    assert test_settings.show_errors is False


def test_noop(test_settings):
    test_settings = test_settings()
    test_settings.update({"mode": "disabled"}, source=Source.BASE)
    assert test_settings._noop is True


def test_attrib_get():
    s = Settings()
    assert s.base_url == "https://api.wandb.ai"


def test_attrib_set_not_allowed():
    s = Settings()
    with pytest.raises(TypeError):
        s.base_url = "new"


def test_attrib_get_bad():
    s = Settings()
    with pytest.raises(AttributeError):
        s.missing  # noqa: B018


def test_update_override():
    s = Settings()
    s.update(dict(base_url="https://something2.local"), source=Source.OVERRIDE)
    assert s.base_url == "https://something2.local"


def test_update_priorities():
    s = Settings()
    # USER has higher priority than ORG (and both are higher priority than BASE)
    s.update(dict(base_url="https://foo.local"), source=Source.USER)
    assert s.base_url == "https://foo.local"
    s.update(dict(base_url="https://bar.local"), source=Source.ORG)
    assert s.base_url == "https://foo.local"


def test_update_priorities_order():
    s = Settings()
    # USER has higher priority than ORG (and both are higher priority than BASE)
    s.update(dict(base_url="https://bar.local"), source=Source.ORG)
    assert s.base_url == "https://bar.local"
    s.update(dict(base_url="https://foo.local"), source=Source.USER)
    assert s.base_url == "https://foo.local"


def test_update_missing_attrib():
    s = Settings()
    with pytest.raises(KeyError):
        s.update(dict(missing="nope"), source=Source.OVERRIDE)


def test_update_kwargs():
    s = Settings()
    s.update(base_url="https://something.local")
    assert s.base_url == "https://something.local"


def test_update_both():
    s = Settings()
    s.update(dict(base_url="https://something.local"), project="nothing")
    assert s.base_url == "https://something.local"
    assert s.project == "nothing"


def test_ignore_globs():
    s = Settings()
    assert s.ignore_globs == ()


def test_ignore_globs_explicit():
    s = Settings(ignore_globs=["foo"])
    assert s.ignore_globs == ("foo",)


def test_ignore_globs_env():
    s = Settings()
    s._apply_env_vars({"WANDB_IGNORE_GLOBS": "foo"})
    assert s.ignore_globs == ("foo",)

    s = Settings()
    s._apply_env_vars({"WANDB_IGNORE_GLOBS": "foo,bar"})
    assert s.ignore_globs == (
        "foo",
        "bar",
    )


def test_quiet():
    s = Settings()
    assert s.quiet is None
    s = Settings(quiet=True)
    assert s.quiet
    s = Settings()
    s._apply_env_vars({"WANDB_QUIET": "false"})
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
    s.update(base_url="https://changed.local")
    s2 = copy.copy(s)
    assert s2.base_url == "https://changed.local"
    s.update(base_url="https://not.changed.local")
    assert s.base_url == "https://not.changed.local"
    assert s2.base_url == "https://changed.local"


def test_update_linked_properties():
    s = Settings()
    # sync_dir depends, among other things, on run_mode
    assert s.mode == "online"
    assert s.run_mode == "run"
    assert ("offline-run" not in s.sync_dir) and ("run" in s.sync_dir)
    s.update(mode="offline")
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

    s.update(mode="offline")
    assert s.mode == "offline"
    assert s.run_mode == "offline-run"
    assert "offline-run" in s.sync_dir
    assert s2.mode == "online"
    assert s2.run_mode == "run"
    assert ("offline-run" not in s2.sync_dir) and ("run" in s2.sync_dir)

    s2.update(mode="offline")
    assert s2.mode == "offline"
    assert s2.run_mode == "offline-run"
    assert "offline-run" in s2.sync_dir


def test_invalid_dict():
    s = Settings()
    with pytest.raises(KeyError):
        s.update(dict(invalid="new"))


def test_invalid_kwargs():
    s = Settings()
    with pytest.raises(KeyError):
        s.update(invalid="new")


def test_invalid_both():
    s = Settings()
    with pytest.raises(KeyError):
        s.update(dict(project="ok"), invalid="new")
    assert s.project != "ok"
    with pytest.raises(KeyError):
        s.update(dict(wrong="bad", entity="nope"), project="okbutnotset")
    assert s.entity != "nope"
    assert s.project != "okbutnotset"


def test_freeze():
    s = Settings()
    s.update(project="goodprojo")
    assert s.project == "goodprojo"
    s.freeze()
    assert s.is_frozen()
    with pytest.raises(TypeError):
        s.update(project="badprojo")
    assert s.project == "goodprojo"
    with pytest.raises(TypeError):
        s.update(project="badprojo2")
    c = copy.copy(s)
    assert c.project == "goodprojo"
    c.update(project="changed")
    assert c.project == "changed"
    assert s.project == "goodprojo"


def test_bad_choice():
    s = Settings()
    with pytest.raises(TypeError):
        s.mode = "goodprojo"
    with pytest.raises(UsageError):
        s.update(mode="badmode")


def test_priority_update_greater_source():
    s = Settings()
    # for a non-policy setting, greater source (PROJECT) has higher priority
    s.update(project="pizza", source=Source.ENTITY)
    assert s.project == "pizza"
    s.update(project="pizza2", source=Source.PROJECT)
    assert s.project == "pizza2"


def test_priority_update_smaller_source():
    s = Settings()
    s.update(project="pizza", source=Source.PROJECT)
    assert s.project == "pizza"
    s.update(project="pizza2", source=Source.ENTITY)
    # for a non-policy setting, greater source (PROJECT) has higher priority
    assert s.project == "pizza"


def test_priority_update_policy_greater_source():
    s = Settings()
    # for a policy setting, greater source (PROJECT) has lower priority
    s.update(summary_warnings=42, source=Source.PROJECT)
    assert s.summary_warnings == 42
    s.update(summary_warnings=43, source=Source.ENTITY)
    assert s.summary_warnings == 43


def test_priority_update_policy_smaller_source():
    s = Settings()
    # for a policy setting, greater source (PROJECT) has lower priority
    s.update(summary_warnings=42, source=Source.ENTITY)
    assert s.summary_warnings == 42
    s.update(summary_warnings=43, source=Source.PROJECT)
    assert s.summary_warnings == 42


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
    "url, error",
    [
        (
            "https://wandb.ai",
            "is not a valid server address, did you mean https://api.wandb.ai?",
        ),
        (
            "https://app.wandb.ai",
            "is not a valid server address, did you mean https://api.wandb.ai?",
        ),
        ("http://api.wandb.ai", "http is not secure, please use https://api.wandb.ai"),
        ("http://host\t.ai", "URL cannot contain unsafe characters"),
        ("http://host\n.ai", "URL cannot contain unsafe characters"),
        ("http://host\r.ai", "URL cannot contain unsafe characters"),
        ("ftp://host.ai", "URL must start with `http(s)://`"),
        (
            "gibberish",
            "gibberish is not a valid server address",
        ),
        ("LOL" * 100, "hostname is invalid"),
    ],
)
def test_validate_invalid_base_url(capsys, url, error):
    s = Settings()
    with pytest.raises(UsageError):
        s.update(base_url=url)
        captured = capsys.readouterr().err
        assert error in captured


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
    s.update(base_url=url)
    assert s.base_url == processed_url


@pytest.mark.parametrize(
    "setting",
    [
        "_disable_meta",
        "_disable_stats",
        "_disable_viewer",
        "disable_code",
        "disable_git",
        "disabled",
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
        s._apply_env_vars(environ=os.environ)
        assert s[setting] is True


@pytest.mark.parametrize(
    "setting, value",
    [
        ("_stats_open_metrics_endpoints", '{"DCGM":"http://localhvost"}'),
        (
            "_stats_open_metrics_filters",
            '{"DCGM_FI_DEV_POWER_USAGE": {"pod": "dcgm-*"}}',
        ),
    ],
)
def test_preprocess_dict_settings(setting: str, value: str):
    with mock.patch.dict(os.environ, {"WANDB_" + setting.upper(): value}):
        s = Settings()
        s._apply_env_vars(environ=os.environ)
        assert s[setting] == json.loads(value)


def test_redact():
    # normal redact case
    redacted = wandb_settings._redact_dict({"this": 2, "that": 9, "api_key": "secret"})
    assert redacted == {"this": 2, "that": 9, "api_key": "***REDACTED***"}

    # two redacted keys with options passed
    redacted = wandb_settings._redact_dict(
        {"ok": "keep", "unsafe": 9, "bad": "secret"},
        unsafe_keys={"unsafe", "bad"},
        redact_str="OMIT",
    )
    assert redacted == {"ok": "keep", "unsafe": "OMIT", "bad": "OMIT"}

    # all keys fine
    redacted = wandb_settings._redact_dict({"all": "keep", "good": 9, "keys": "fine"})
    assert redacted == {"all": "keep", "good": 9, "keys": "fine"}

    # empty case
    redacted = wandb_settings._redact_dict({})
    assert redacted == {}

    # all keys redacted
    redacted = wandb_settings._redact_dict({"api_key": "secret"})
    assert redacted == {"api_key": "***REDACTED***"}


def test_strict():
    settings = Settings(strict=True)
    assert settings.strict is True

    settings = Settings(strict=False)
    assert not settings.strict


def test_validate_console_problem_anonymous():
    s = Settings()
    with pytest.raises(UsageError):
        s.update(console="lol")
    with pytest.raises(UsageError):
        s.update(problem="lol")
    with pytest.raises(UsageError):
        s.update(anonymous="lol")


def test_wandb_dir(test_settings):
    test_settings = test_settings()
    assert os.path.abspath(test_settings.wandb_dir) == os.path.abspath("wandb")


def test_resume_fname(test_settings):
    test_settings = test_settings()
    assert test_settings.resume_fname == os.path.abspath(
        os.path.join(".", "wandb", "wandb-resume.json")
    )


@pytest.mark.skip(reason="CircleCI still lets you write to root_dir")
def test_non_writable_root_dir(capsys):
    with CliRunner().isolated_filesystem():
        root_dir = os.getcwd()
        s = Settings()
        s.update(root_dir=root_dir)
        # make root_dir non-writable
        os.chmod(root_dir, 0o444)
        wandb_dir = s.wandb_dir
        assert wandb_dir != "/wandb"
        _, err = capsys.readouterr()
        assert "wasn't writable, using system temp directory" in err


def test_log_user(test_settings):
    test_settings = test_settings({"run_id": "test"})
    _, run_dir, log_dir, fname = os.path.abspath(
        os.path.realpath(test_settings.log_user)
    ).rsplit(os.path.sep, 3)
    _, _, run_id = run_dir.split("-")
    assert run_id == test_settings.run_id
    assert log_dir == "logs"
    assert fname == "debug.log"


def test_log_internal(test_settings):
    test_settings = test_settings({"run_id": "test"})
    _, run_dir, log_dir, fname = os.path.abspath(
        os.path.realpath(test_settings.log_internal)
    ).rsplit(os.path.sep, 3)
    _, _, run_id = run_dir.split("-")
    assert run_id == test_settings.run_id
    assert log_dir == "logs"
    assert fname == "debug-internal.log"


class TestAsyncUploadConcurrency:
    def test_default_is_none(self, test_settings):
        settings = test_settings()
        assert settings._async_upload_concurrency_limit is None

    @pytest.mark.parametrize(
        ["value", "ok"],
        [
            (None, True),
            (1, True),
            (2, True),
            (10, True),
            (100, True),
            (99999999, True),
            (-10, False),
            ("not an int", False),
        ],
    )
    def test_err_iff_bad_value(self, value: Optional[int], ok: bool, test_settings):
        if ok:
            settings = test_settings({"_async_upload_concurrency_limit": value})
            assert settings._async_upload_concurrency_limit == value
        else:
            with pytest.raises((UsageError, ValueError)):
                test_settings({"_async_upload_concurrency_limit": value})

    @pytest.mark.parametrize(
        ["value", "warn"], [(None, False), (1, False), (9999999, True)]
    )
    @mock.patch("wandb.termwarn")
    def test_warns_if_exceeds_filelimit(
        self,
        termwarn: mock.Mock,
        test_settings,
        value: Optional[int],
        warn: bool,
    ):
        pytest.importorskip("resource")
        test_settings({"_async_upload_concurrency_limit": value})

        if warn:
            termwarn.assert_called_once()
            assert "exceeds this process's limit" in termwarn.call_args[0][0]
        else:
            termwarn.assert_not_called()


# --------------------------
# test static settings
# --------------------------


def test_settings_static():
    from wandb.sdk.internal.settings_static import SettingsStatic

    static_settings = SettingsStatic(Settings().make_static())
    assert "base_url" in static_settings
    assert static_settings.get("base_url") == "https://api.wandb.ai"


# --------------------------
# test run settings
# --------------------------


def test_silent_run(mock_run, test_settings):
    test_settings = test_settings()
    test_settings.update({"silent": "true"}, source=Source.SETTINGS)
    assert test_settings.silent is True
    run = mock_run(settings=test_settings)
    assert run._settings.silent is True


def test_strict_run(mock_run, test_settings):
    test_settings = test_settings()
    test_settings.update({"strict": "true"}, source=Source.SETTINGS)
    assert test_settings.strict is True
    run = mock_run(settings=test_settings)
    assert run._settings.strict is True


def test_show_info_run(mock_run):
    run = mock_run()
    assert run._settings.show_info is True


def test_show_info_false_run(mock_run, test_settings):
    test_settings = test_settings()
    test_settings.update({"show_info": "false"}, source=Source.SETTINGS)
    run = mock_run(settings=test_settings)
    assert run._settings.show_info is False


def test_show_warnings_run(mock_run, test_settings):
    test_settings = test_settings()
    test_settings.update({"show_warnings": "true"}, source=Source.SETTINGS)
    run = mock_run(settings=test_settings)
    assert run._settings.show_warnings is True


def test_show_warnings_false_run(mock_run, test_settings):
    test_settings = test_settings()
    test_settings.update({"show_warnings": "false"}, source=Source.SETTINGS)
    run = mock_run(settings=test_settings)
    assert run._settings.show_warnings is False


def test_show_errors_run(mock_run, test_settings):
    test_settings = test_settings()
    test_settings.update({"show_errors": True}, source=Source.SETTINGS)
    run = mock_run(settings=test_settings)
    assert run._settings.show_errors is True


def test_show_errors_false_run(mock_run, test_settings):
    test_settings = test_settings()
    test_settings.update({"show_errors": False}, source=Source.SETTINGS)
    run = mock_run(settings=test_settings)
    assert run._settings.show_errors is False


def test_not_jupyter(mock_run):
    run = mock_run()
    assert run._settings._jupyter is False


def test_resume_fname_run(mock_run):
    run = mock_run()
    assert run._settings.resume_fname == os.path.join(
        run._settings.root_dir, "wandb", "wandb-resume.json"
    )


def test_wandb_dir_run(mock_run):
    run = mock_run()
    assert os.path.abspath(run._settings.wandb_dir) == os.path.abspath(
        os.path.join(run._settings.root_dir, "wandb")
    )


def test_console_run(mock_run):
    run = mock_run(settings={"console": "auto", "mode": "offline"})
    assert run._settings.console == "auto"
    assert run._settings._console == wandb_settings.SettingsConsole.WRAP


def test_console(test_settings):
    test_settings = test_settings()
    assert test_settings._console == wandb_settings.SettingsConsole.OFF
    test_settings.update({"console": "redirect"}, source=Source.BASE)
    assert test_settings._console == wandb_settings.SettingsConsole.REDIRECT
    test_settings.update({"console": "wrap"}, source=Source.BASE)
    assert test_settings._console == wandb_settings.SettingsConsole.WRAP


def test_code_saving_save_code_env_false(mock_run, test_settings):
    settings = test_settings()
    settings.update({"save_code": None}, source=Source.BASE)
    with mock.patch.dict("os.environ", WANDB_SAVE_CODE="false"):
        settings._infer_settings_from_environment()
        run = mock_run(settings=settings)
        assert run._settings.save_code is False


def test_code_saving_disable_code(mock_run, test_settings):
    settings = test_settings()
    settings.update({"save_code": None}, source=Source.BASE)
    with mock.patch.dict("os.environ", WANDB_DISABLE_CODE="true"):
        settings._infer_settings_from_environment()
        run = mock_run(settings=settings)
        assert run.settings.save_code is False


def test_override_login_settings(test_settings):
    wlogin = wandb_login._WandbLogin()
    login_settings = test_settings().copy()
    login_settings.update(show_emoji=True)
    wlogin.setup({"_settings": login_settings})
    assert wlogin._settings.show_emoji is True


def test_override_login_settings_with_dict():
    wlogin = wandb_login._WandbLogin()
    login_settings = dict(show_emoji=True)
    wlogin.setup({"_settings": login_settings})
    assert wlogin._settings.show_emoji is True


def test_setup_offline(test_settings):
    # this is to increase coverage
    login_settings = test_settings().copy()
    login_settings.update(mode="offline")
    assert wandb.setup(settings=login_settings)._instance._get_entity() is None
    assert wandb.setup(settings=login_settings)._instance._load_viewer() is None


@pytest.mark.skip(reason="causes other tests that depend on capsys to fail")
def test_silent_env_run(mock_run, test_settings):
    settings = test_settings()
    with mock.patch.dict("os.environ", WANDB_SILENT="true"):
        settings._apply_env_vars(os.environ)
        run = mock_run(settings=settings)
        assert run._settings.silent is True
