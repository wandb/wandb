"""
settings test.
"""
from datetime import datetime
import pytest  # type: ignore

import wandb
from wandb import Settings
from wandb.sdk.wandb_settings import SettingsConsole
import os
import copy


def get_formatted_datetime(run_datetime):
    return datetime.strftime(run_datetime, "%Y%m%d_%H%M%S")


def test_attrib_get():
    s = Settings()
    s.setdefaults()
    assert s.base_url == "https://api.wandb.ai"


def test_attrib_set():
    s = Settings()
    s.base_url = "this"
    assert s.base_url == "this"


def test_attrib_get_bad():
    s = Settings()
    with pytest.raises(AttributeError):
        s.missing


def test_attrib_set_bad():
    s = Settings()
    with pytest.raises(AttributeError):
        s.missing = "nope"


def test_update_dict():
    s = Settings()
    s.update(dict(base_url="something2"))
    assert s.base_url == "something2"


def test_update_kwargs():
    s = Settings()
    s.update(base_url="something")
    assert s.base_url == "something"


def test_update_both():
    s = Settings()
    s.update(dict(base_url="somethingb"), project="nothing")
    assert s.base_url == "somethingb"
    assert s.project == "nothing"


def test_ignore_globs():
    s = Settings()
    s.setdefaults()
    assert s.ignore_globs == ()


def test_ignore_globs_explicit():
    s = Settings(ignore_globs=["foo"])
    s.setdefaults()
    assert s.ignore_globs == ("foo",)


def test_ignore_globs_env():
    s = Settings()
    s._apply_environ({"WANDB_IGNORE_GLOBS": "foo,bar"})
    s.setdefaults()
    assert s.ignore_globs == ("foo", "bar",)


@pytest.mark.skip(reason="I need to make my mock work properly with new settings")
def test_ignore_globs_settings(local_settings):
    with open(os.path.join(os.getcwd(), ".config", "wandb", "settings"), "w") as f:
        f.write(
            """[default]
ignore_globs=foo,bar"""
        )
    s = Settings(_files=True)
    s.setdefaults()
    assert s.ignore_globs == ("foo", "bar",)


def test_copy():
    s = Settings()
    s.update(base_url="changed")
    s2 = copy.copy(s)
    assert s2.base_url == "changed"
    s.update(base_url="notchanged")
    assert s.base_url == "notchanged"
    assert s2.base_url == "changed"


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
    s.project = "goodprojo"
    assert s.project == "goodprojo"
    s.freeze()
    with pytest.raises(TypeError):
        s.project = "badprojo"
    assert s.project == "goodprojo"
    with pytest.raises(TypeError):
        s.update(project="badprojo2")
    assert s.project == "goodprojo"
    c = copy.copy(s)
    assert c.project == "goodprojo"
    c.project = "changed"
    assert c.project == "changed"


def test_bad_choice():
    s = Settings()
    with pytest.raises(TypeError):
        s.mode = "goodprojo"
    with pytest.raises(TypeError):
        s.update(mode="badpro")


def test_prio_update_ok():
    s = Settings()
    s.update(project="pizza", _source=s.Source.ENTITY)
    assert s.project == "pizza"
    s.update(project="pizza2", _source=s.Source.PROJECT)
    assert s.project == "pizza2"


def test_prio_update_ignore():
    s = Settings()
    s.update(project="pizza", _source=s.Source.PROJECT)
    assert s.project == "pizza"
    s.update(project="pizza2", _source=s.Source.ENTITY)
    assert s.project == "pizza"


def test_prio_update_over_ok():
    s = Settings()
    s.update(project="pizza", _source=s.Source.PROJECT)
    assert s.project == "pizza"
    s.update(project="pizza2", _source=s.Source.ENTITY, _override=True)
    assert s.project == "pizza2"


def test_prio_update_over_both_ok():
    s = Settings()
    s.update(project="pizza", _source=s.Source.PROJECT, _override=True)
    assert s.project == "pizza"
    s.update(project="pizza2", _source=s.Source.ENTITY, _override=True)
    assert s.project == "pizza2"


def test_prio_update_over_ignore():
    s = Settings()
    s.update(project="pizza", _source=s.Source.ENTITY, _override=True)
    assert s.project == "pizza"
    s.update(project="pizza2", _source=s.Source.PROJECT, _override=True)
    assert s.project == "pizza"


def test_prio_context_ok():
    s = Settings()
    s.update(project="pizza", _source=s.Source.ENTITY)
    assert s.project == "pizza"
    with s._as_source(s.Source.PROJECT) as s2:
        s2.project = "pizza2"
    assert s.project == "pizza2"


def test_prio_context_ignore():
    s = Settings()
    s.update(project="pizza", _source=s.Source.PROJECT)
    assert s.project == "pizza"
    with s._as_source(s.Source.ENTITY) as s2:
        s2.project = "pizza2"
    assert s.project == "pizza"


def test_prio_context_over_ok():
    s = Settings()
    s.update(project="pizza", _source=s.Source.PROJECT)
    assert s.project == "pizza"
    with s._as_source(s.Source.ENTITY, override=True) as s2:
        s2.project = "pizza2"
    assert s.project == "pizza2"


def test_prio_context_over_both_ok():
    s = Settings()
    s.update(project="pizza", _source=s.Source.PROJECT, _override=True)
    assert s.project == "pizza"
    with s._as_source(s.Source.ENTITY, override=True) as s2:
        s2.project = "pizza2"
    assert s.project == "pizza2"


def test_prio_context_over_ignore():
    s = Settings()
    s.update(project="pizza", _source=s.Source.ENTITY, _override=True)
    assert s.project == "pizza"
    with s._as_source(s.Source.PROJECT, override=True) as s2:
        s2.project = "pizza2"
    assert s.project == "pizza"


def test_validate_base_url():
    s = Settings()
    with pytest.raises(TypeError):
        s.update(base_url="https://wandb.ai")
    with pytest.raises(TypeError):
        s.update(base_url="https://app.wandb.ai")
    with pytest.raises(TypeError):
        s.update(base_url="http://api.wandb.ai")
    s.update(base_url="https://api.wandb.ai")
    assert s.base_url == "https://api.wandb.ai"
    s.update(base_url="https://wandb.ai.other.crazy.domain.com")
    assert s.base_url == "https://wandb.ai.other.crazy.domain.com"


def test_preprocess_base_url():
    s = Settings()
    s.update(base_url="http://host.com")
    assert s.base_url == "http://host.com"
    s.update(base_url="http://host.com/")
    assert s.base_url == "http://host.com"
    s.update(base_url="http://host.com///")
    assert s.base_url == "http://host.com"
    s.update(base_url="//http://host.com//")
    assert s.base_url == "//http://host.com"


def test_code_saving_save_code_env_false(live_mock_server, test_settings):
    test_settings.update({"save_code": None})
    os.environ["WANDB_SAVE_CODE"] = "false"
    run = wandb.init(settings=test_settings)
    assert run._settings.save_code is False


def test_code_saving_disable_code(live_mock_server, test_settings):
    test_settings.update({"save_code": None})
    os.environ["WANDB_DISABLE_CODE"] = "true"
    run = wandb.init(settings=test_settings)
    assert run._settings.save_code is False


def test_offline(test_settings):
    assert test_settings._offline is False
    test_settings.update({"disabled": True})
    assert test_settings._offline is True
    test_settings.update({"disabled": None})
    test_settings.update({"mode": "dryrun"})
    assert test_settings._offline is True
    test_settings.update({"mode": "offline"})
    assert test_settings._offline is True


def test_offline_run(live_mock_server, test_settings):
    run = wandb.init(settings=test_settings)
    assert run._settings._offline is False
    test_settings.update({"disabled": True})
    run = wandb.init(settings=test_settings)
    assert run._settings._offline is True
    test_settings.update({"disabled": None})
    test_settings.update({"mode": "dryrun"})
    run = wandb.init(settings=test_settings)
    assert run._settings._offline is True
    test_settings.update({"mode": "offline"})
    run = wandb.init(settings=test_settings)
    assert run._settings._offline is True


def test_silent(live_mock_server, test_settings):
    test_settings.update({"silent": "true"})
    assert test_settings._silent is True


@pytest.mark.skip(reason="Setting silent via settings doesn't work")
def test_silent_run(live_mock_server, test_settings):
    test_settings.update({"silent": "true"})
    run = wandb.init(settings=test_settings)
    assert run._settings._silent is True


def test_silent_env_run(live_mock_server, test_settings, capsys):
    os.environ["WANDB_SILENT"] = "true"
    run = wandb.init(settings=test_settings)
    assert run._settings._silent is True
    captured = capsys.readouterr()
    assert len(captured.out) == 0


def test_strict(test_settings):
    test_settings.update({"strict": "true"})
    assert test_settings._strict is True

    test_settings.update({"strict": "false"})
    assert test_settings._strict is False


@pytest.mark.skip(reason="Setting strict false via settings doesn't work")
def test_strict_run(live_mock_server, test_settings):
    test_settings.update({"strict": "true"})
    assert test_settings._strict is True
    run = wandb.init(settings=test_settings)
    assert run._settings._strict is True

    test_settings.update({"strict": "false"})
    assert test_settings._strict is False
    run = wandb.init(settings=test_settings)
    assert run._settings._strict is False


def test_show_info(test_settings):
    test_settings.update({"show_info": True})
    assert test_settings._show_info is True

    test_settings.update({"show_info": False})
    assert test_settings._show_info is False


@pytest.mark.skip(reason="Setting show_info false via settings doesn't work")
def test_show_info_run(live_mock_server, test_settings):
    test_settings.update({"show_info": True})
    run = wandb.init(settings=test_settings)
    assert run._settings._show_info is True

    test_settings.update({"show_info": False})
    run = wandb.init(settings=test_settings)
    assert run._settings._show_info is False


def test_show_warnings(test_settings):
    test_settings.update({"show_warnings": "true"})
    assert test_settings._show_warnings is True

    test_settings.update({"show_warnings": "false"})
    assert test_settings._show_warnings is False


@pytest.mark.skip(reason="Setting show_warnings false via settings doesn't work")
def test_show_warnings_run(live_mock_server, test_settings):
    test_settings.update({"show_warnings": "true"})
    run = wandb.init(settings=test_settings)
    assert run._settings._show_warnings is True

    test_settings.update({"show_warnings": "false"})
    run = wandb.init(settings=test_settings)
    assert run._settings._show_warnings is False


def test_show_errors(test_settings):
    test_settings.update({"show_errors": True})
    assert test_settings._show_errors is True

    test_settings.update({"show_errors": False})
    assert test_settings._show_errors is False


@pytest.mark.skip(reason="Setting show_errors false via settings doesn't work")
def test_show_errors_run(test_settings):
    test_settings.update({"show_errors": True})
    run = wandb.init(settings=test_settings)
    assert run._settings._show_errors is True

    test_settings.update({"show_errors": False})
    run = wandb.init(settings=test_settings)
    assert run._settings._show_errors is False


def test_noop(test_settings):
    test_settings.update({"disabled": "true"})
    assert test_settings._noop is True


def test_noop_run(live_mock_server, test_settings):
    test_settings.update({"disabled": "true"})
    run = wandb.init(settings=test_settings)
    assert run._settings._noop is True


def test_jupyter(notebook):
    with notebook("one_cell.ipynb") as nb:
        nb.execute_all()
        output = nb.cell_output(0)
        assert "is_jupyter: True\n" in output[-1]["text"]


def test_not_jupyter(test_settings):
    run = wandb.init(settings=test_settings)
    assert run._settings._jupyter is False


def test_kaggle():
    pass


def test_console(test_settings):
    run = wandb.init(settings=test_settings)
    assert run._settings._console == SettingsConsole.OFF
    test_settings.update({"console": "auto"})
    assert test_settings._console == SettingsConsole.REDIRECT
    test_settings.update({"console": "wrap"})
    assert test_settings._console == SettingsConsole.WRAP


def test_console_run(test_settings):
    run = wandb.init(settings=test_settings)
    assert run._settings._console == SettingsConsole.OFF
    # commented out because you can't set console using settings
    # test_settings.update({"console": "auto"})
    # run = wandb.init(settings=test_settings)
    # assert run._settings._console == SettingsConsole.REDIRECT
    # os.environ["WANDB_START_METHOD"] = "thread"
    # run = wandb.init(settings=test_settings)
    # assert run._settings._console == SettingsConsole.WRAP


def test_resume_fname(test_settings):
    assert test_settings.resume_fname == os.path.join("./wandb", "wandb-resume.json")


def test_resume_fname_run(test_settings):
    run = wandb.init(settings=test_settings)
    assert run._settings.resume_fname == os.path.join(
        run._settings.root_dir, "wandb", "wandb-resume.json"
    )


def test_wandb_dir(test_settings):
    assert os.path.abspath(test_settings.wandb_dir) == os.path.abspath("wandb/")


def test_wandb_dir_run(test_settings):
    run = wandb.init(settings=test_settings)
    assert os.path.abspath(run._settings.wandb_dir) == os.path.abspath(
        os.path.join(run._settings.root_dir, "wandb/")
    )


def test_log_user(test_settings):
    assert os.path.abspath(test_settings.log_user) == os.path.realpath(
        "./wandb/latest-run/logs/debug.log"
    )


def test_log_user_run(test_settings):
    run = wandb.init(settings=test_settings)
    assert os.path.abspath(run._settings.log_user) == os.path.realpath(
        "./wandb/latest-run/logs/debug.log"
    )


def test_log_internal(test_settings):
    assert os.path.abspath(test_settings.log_internal) == os.path.realpath(
        "./wandb/latest-run/logs/debug-internal.log"
    )


def test_log_internal_run(test_settings):
    run = wandb.init(settings=test_settings)
    assert os.path.abspath(run._settings.log_internal) == os.path.realpath(
        "./wandb/latest-run/logs/debug-internal.log"
    )


def test_sync_dir_run(test_settings):
    run = wandb.init(settings=test_settings)
    assert run._settings._sync_dir == os.path.realpath("./wandb/latest-run")


def test_sync_file_run(test_settings):
    run = wandb.init(settings=test_settings)
    assert run._settings.sync_file == os.path.realpath(
        "./wandb/latest-run/run-{}.wandb".format(run.id)
    )


def test_files_dir(test_settings):
    run = wandb.init(settings=test_settings)
    assert run._settings.files_dir == os.path.realpath("./wandb/latest-run/files")


def test_tmp_dir(test_settings):
    run = wandb.init(settings=test_settings)
    assert run._settings.tmp_dir == os.path.realpath("./wandb/latest-run/tmp")


def test_tmp_code_dir(test_settings):
    run = wandb.init(settings=test_settings)
    assert run._settings.tmp_dir == os.path.realpath("./wandb/latest-run/tmp/code")


def test_log_symlink_user(test_settings):
    run = wandb.init(settings=test_settings)
    assert os.path.realpath(run._settings.log_symlink_user) == os.path.abspath(
        run._settings.log_user
    )


def test_log_symlink_internal(test_settings):
    run = wandb.init(settings=test_settings)
    assert os.path.realpath(run._settings.log_symlink_internal) == os.path.abspath(
        run._settings.log_internal
    )


def test_sync_symlink_latest(test_settings):
    run = wandb.init(settings=test_settings)
    assert os.path.realpath(run._settings.sync_symlink_latest) == os.path.abspath(
        "./wandb/run-{}-{}".format(
            get_formatted_datetime(run._settings._start_datetime), run.id
        )
    )


def test_settings_system(test_settings):
    assert test_settings.settings_system == os.path.abspath("~/.config/wandb/settings")


def test_settings_system_run(test_settings):
    run = wandb.init(settings=test_settings)
    assert run._settings.settings_system == os.path.abspath("~/.config/wandb/settings")


def test_path_convert(test_settings):
    pass


def test_setup(test_settings):
    # appears unused
    pass
