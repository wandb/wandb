import pathlib
import re
import textwrap

import pytest
from wandb.sdk.lib import settings_file

from tests.fixtures.mock_wandb_log import MockWandbLog


def test_error_writing(tmp_path: pathlib.Path):
    local_settings = tmp_path / "local_settings"
    local_settings.mkdir()  # Cannot read or write a directory.

    system_settings = settings_file.SettingsFiles(
        global_settings=None,
        local_settings=local_settings,
    )
    system_settings.set("x", "value")

    with pytest.raises(
        settings_file.SaveSettingsError,
        match=f"Error updating settings at {re.escape(str(local_settings))}",
    ):
        system_settings.save()


def test_error_reading(tmp_path: pathlib.Path, mock_wandb_log: MockWandbLog):
    local_settings = tmp_path / "local_settings"
    local_settings.write_text("oops - invalid format")

    settings_file.SettingsFiles(
        global_settings=None,
        local_settings=local_settings,
    )

    mock_wandb_log.assert_warned(f"Error reading settings at {local_settings}")


def test_write_local_settings(
    tmp_path: pathlib.Path,
    mock_wandb_log: MockWandbLog,
):
    local_settings = tmp_path / "local_settings"

    system_settings = settings_file.SettingsFiles(
        global_settings=None,
        local_settings=local_settings,
    )
    system_settings.set("x", "x-value")
    system_settings.set("y", "y-value")
    system_settings.save()

    assert local_settings.read_text().splitlines() == [
        "[default]",
        "x = x-value",
        "y = y-value",
        "",
    ]
    mock_wandb_log.assert_logged(f"Updated settings file {local_settings}")


def test_write_global_settings(
    tmp_path: pathlib.Path,
    mock_wandb_log: MockWandbLog,
):
    global_settings = tmp_path / "global_settings"
    local_settings = tmp_path / "local_settings"

    system_settings = settings_file.SettingsFiles(
        global_settings=global_settings,
        local_settings=local_settings,
    )
    system_settings.set("x", "x-value", globally=True)
    system_settings.set("y", "y-value", globally=True)
    system_settings.save()

    assert not local_settings.exists()
    assert global_settings.read_text().splitlines() == [
        "[default]",
        "x = x-value",
        "y = y-value",
        "",
    ]
    mock_wandb_log.assert_logged(f"Updated settings file {global_settings}")


def test_precedence(tmp_path: pathlib.Path):
    global_settings = tmp_path / "global_settings"
    global_settings.write_text(
        textwrap.dedent("""\
            [default]
            x = global
            y = global-y
        """)
    )
    local_settings1 = tmp_path / "local_settings1"
    local_settings1.write_text(
        textwrap.dedent("""\
            [default]
            x = local-1
            z = local-1-z
        """)
    )
    local_settings2 = tmp_path / "local_settings2"
    local_settings2.write_text(
        textwrap.dedent("""\
            [default]
            x = local-2
            z = local-2-z
        """)
    )

    system_settings1 = settings_file.SettingsFiles(
        global_settings=global_settings,
        local_settings=local_settings1,
    )
    system_settings2 = settings_file.SettingsFiles(
        global_settings=global_settings,
        local_settings=local_settings2,
    )

    assert system_settings1.all() == {
        "x": "local-1",
        "y": "global-y",
        "z": "local-1-z",
    }
    assert system_settings2.all() == {
        "x": "local-2",
        "y": "global-y",
        "z": "local-2-z",
    }


def test_set_locally_and_globally(tmp_path: pathlib.Path):
    global_settings = tmp_path / "global_settings"
    local_settings = tmp_path / "local_settings"

    system_settings = settings_file.SettingsFiles(
        global_settings=global_settings,
        local_settings=local_settings,
    )
    system_settings.set("x", "local")
    system_settings.set("y", "global", globally=True)
    system_settings.save()

    assert global_settings.read_text().splitlines() == [
        "[default]",
        "y = global",
        "",
    ]
    assert local_settings.read_text().splitlines() == [
        "[default]",
        "x = local",
        "",
    ]


def test_clear_locally_and_globally(tmp_path: pathlib.Path):
    global_settings = tmp_path / "global_settings"
    global_settings.write_text(
        textwrap.dedent("""\
            [default]
            x = global-x
            y = global-y
            z = global-z
        """)
    )
    local_settings = tmp_path / "local_settings"
    local_settings.write_text(
        textwrap.dedent("""\
            [default]
            x = local-x
            y = local-y
            z = local-z
        """)
    )

    system_settings = settings_file.SettingsFiles(
        global_settings=global_settings,
        local_settings=local_settings,
    )
    system_settings.clear("x")
    system_settings.clear("y", globally=True)
    system_settings.save()

    assert global_settings.read_text().splitlines() == [
        "[default]",
        "x = global-x",
        "z = global-z",
        "",
    ]
    assert local_settings.read_text().splitlines() == [
        "[default]",
        "z = local-z",
        "",
    ]
