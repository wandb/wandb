import io
import json
import os
import pathlib
import re
import subprocess
import sys
from unittest import mock

import nbformat
import pytest
import wandb
import wandb.sdk.lib.ipython as wb_ipython
import wandb.util


def test_login_timeout(notebook):
    with notebook("login_timeout.ipynb", skip_api_key_env=True) as nb:
        nb.execute_all()
        output = nb.cell_output_text(1)
        assert "W&B disabled due to login timeout" in output

        output = nb.cell_output(1)
        assert output[-1]["data"]["text/plain"] == "False"


def test_one_cell(notebook, run_id):
    with notebook("one_cell.ipynb") as nb:
        nb.execute_all()
        output = nb.cell_output_html(2)
        assert run_id in output


def test_init_finishes_previous_by_default(notebook):
    with notebook("init_finishes_previous.ipynb") as nb:
        nb.execute_all()
        output = nb.cell_output_text(1)
        assert output == "run1 finished? True\nrun1 is run2? False\n"


def test_magic(notebook):
    with notebook("magic.ipynb") as nb:
        nb.execute_all()

        assert "<iframe" in nb.cell_output_html(0)
        assert "CommError" in nb.cell_output_text(1)
        assert nb.cell_output_html(1) == (
            "Path 'does/not/exist' does not refer to a W&B object you can access."
        )


def test_notebook_exits(user, assets_path):
    nb_path = pathlib.Path("notebooks") / "ipython_exit.py"
    script_fname = assets_path(nb_path)
    bindir = os.path.dirname(sys.executable)
    ipython = os.path.join(bindir, "ipython")
    cmd = [ipython, script_fname]
    subprocess.check_call(cmd)


def test_notebook_metadata_jupyter(mocked_module, notebook):
    base_url = os.getenv("WANDB_BASE_URL")
    assert base_url

    with mock.patch("ipykernel.connect.get_connection_file") as ipyconnect:
        ipyconnect.return_value = "kernel-12345.json"
        serverapp = mocked_module("jupyter_server.serverapp")
        serverapp.list_running_servers.return_value = [
            {"url": base_url, "notebook_dir": "/test"}
        ]
        with mock.patch.object(
            wandb.jupyter.requests,
            "get",
            lambda *args, **kwargs: mock.MagicMock(
                json=lambda: [
                    {
                        "kernel": {"id": "12345"},
                        "notebook": {
                            "name": "test.ipynb",
                            "path": "test.ipynb",
                        },
                    }
                ]
            ),
        ):
            meta = wandb.jupyter.notebook_metadata(False)
            assert meta == {"path": "test.ipynb", "root": "/test", "name": "test.ipynb"}


def test_notebook_metadata_no_servers(mocked_module):
    with mock.patch("ipykernel.connect.get_connection_file") as ipyconnect:
        ipyconnect.return_value = "kernel-12345.json"
        serverapp = mocked_module("jupyter_server.serverapp")
        serverapp.list_running_servers.return_value = []
        meta = wandb.jupyter.notebook_metadata(False)
        assert meta == {}


def test_notebook_metadata_colab(mocked_module):
    # Needed for patching due to the lazy-load set up in wandb/__init__.py
    import wandb.jupyter

    colab = mocked_module("google.colab")
    colab._message.blocking_request.return_value = {
        "ipynb": {"metadata": {"colab": {"name": "koalab.ipynb"}}}
    }
    with mock.patch.object(
        wandb.jupyter,
        "notebook_metadata_from_jupyter_servers_and_kernel_id",
        lambda *args, **kwargs: {
            "path": "colab.ipynb",
            "root": "/consent",
            "name": "colab.ipynb",
        },
    ):
        wandb.jupyter.notebook_metadata_from_jupyter_servers_and_kernel_id()
        meta = wandb.jupyter.notebook_metadata(False)
        assert meta == {
            "root": "/content",
            "path": "colab.ipynb",
            "name": "colab.ipynb",
        }


def test_notebook_metadata_kaggle(mocked_module):
    # Needed for patching due to the lazy-load set up in wandb/__init__.py
    import wandb.jupyter

    os.environ["KAGGLE_KERNEL_RUN_TYPE"] = "test"
    kaggle = mocked_module("kaggle_session")
    kaggle_client = mock.MagicMock()
    kaggle_client.get_exportable_ipynb.return_value = {
        "source": json.dumps({"metadata": {}, "cells": []})
    }
    kaggle.UserSessionClient.return_value = kaggle_client
    with mock.patch.object(
        wandb.jupyter,
        "notebook_metadata_from_jupyter_servers_and_kernel_id",
        lambda *args, **kwargs: {},
    ):
        meta = wandb.jupyter.notebook_metadata(False)
        assert meta == {
            "root": "/kaggle/working",
            "path": "kaggle.ipynb",
            "name": "kaggle.ipynb",
        }


def test_notebook_not_exists(mocked_ipython, user, capsys):
    with mock.patch.dict(os.environ, {"WANDB_NOTEBOOK_NAME": "fake.ipynb"}):
        run = wandb.init()
        _, err = capsys.readouterr()
        assert "WANDB_NOTEBOOK_NAME should be a path" in err
        run.finish()


def test_mocked_notebook_html_default(user, run_id, mocked_ipython):
    wandb.load_ipython_extension(mocked_ipython)
    mocked_ipython.register_magics.assert_called_with(wandb.jupyter.WandBMagics)
    with wandb.init(id=run_id) as run:
        run.log({"acc": 99, "loss": 0})
        run.finish()
    displayed_html = [args[0].strip() for args, _ in mocked_ipython.html.call_args_list]
    for i, html in enumerate(displayed_html):
        print(f"[{i}]: {html}")
    assert any(run_id in html for html in displayed_html)
    assert any("Run history:" in html for html in displayed_html)


def test_mocked_notebook_html_quiet(user, run_id, mocked_ipython):
    run = wandb.init(id=run_id, settings=wandb.Settings(quiet=True))
    run.log({"acc": 99, "loss": 0})
    run.finish()
    displayed_html = [args[0].strip() for args, _ in mocked_ipython.html.call_args_list]
    for i, html in enumerate(displayed_html):
        print(f"[{i}]: {html}")
    assert any(run_id in html for html in displayed_html)
    assert not any("Run history:" in html for html in displayed_html)


@pytest.mark.parametrize(
    "vsc_ipynb_value, expected_result",
    [
        ("/path/to/notebook.ipynb", True),
        (None, False),
    ],
    ids=["returns_true", "returns_false"],
)
def test_ipython_in_vscode_notebook(
    mocked_ipython,
    vsc_ipynb_value,
    expected_result,
):
    mocked_ipython.kernel.shell.user_ns["__vsc_ipynb_file__"] = vsc_ipynb_value
    assert wb_ipython.in_vscode_notebook() == expected_result


def test_mocked_notebook_run_display_vscode(user, mocked_ipython):
    import html

    _ = user
    mocked_ipython.kernel.shell.user_ns["__vsc_ipynb_file__"] = (
        "/path/to/notebook.ipynb"
    )

    with wandb.init() as run:
        run.display()

    api = wandb.Api()
    api_run = api.run(f"{run.entity}/{run.project}/{run.id}")
    assert api_run._repr_html_() == html.escape(api_run._string_representation())


def test_mocked_notebook_run_display(user, mocked_ipython):
    _ = user
    mocked_ipython.kernel.shell.user_ns["__vsc_ipynb_file__"] = None

    with wandb.init() as run:
        run.display()

    api = wandb.Api()
    api_run = api.run(f"{run.entity}/{run.project}/{run.id}")
    assert api_run._repr_html_() == api_run.to_html()


def test_api_run_in_in_vscode_does_not_show_iframe(notebook):
    with notebook("api_run_display.ipynb") as nb:
        setup_cell = io.StringIO()
        setup_cell.write(
            "from IPython import get_ipython\n"
            'get_ipython().kernel.shell.user_ns["__vsc_ipynb_file__"] = "api_run_display.ipynb"',
        )
        nb.nb.cells.insert(0, nbformat.v4.new_code_cell(setup_cell.getvalue()))

        nb.execute_all()

        cell = nb.nb.cells[-1]
        cell_output = cell["outputs"][0]
        html = cell_output["data"]["text/html"]
        assert "<iframe" not in html


def test_code_saving(notebook):
    with notebook("code_saving.ipynb", save_code=False) as nb:
        nb.execute_all()
        assert "Failed to detect the name of this notebook" in nb.all_output_text()

    # Let's make sure we warn the user if they lie to us.
    with notebook("code_saving.ipynb") as nb:
        os.remove("code_saving.ipynb")
        nb.execute_all()
        assert "WANDB_NOTEBOOK_NAME should be a path" in nb.all_output_text()


def test_notebook_creates_artifact_job(notebook):
    with notebook("one_cell_disable_git.ipynb") as nb:
        nb.execute_all()
        output = nb.cell_output_html(2)
    # get the run id from the url in the output
    regex_string = r'http:\/\/localhost:\d+\/[^\/]+\/[^\/]+\/runs\/([^\'"]+)'
    run_id = re.search(regex_string, str(output)).group(1)

    api = wandb.Api()
    user = os.environ["WANDB_USERNAME"]
    run = api.run(f"{user}/uncategorized/{run_id}")
    used_artifacts = run.used_artifacts()
    assert len(used_artifacts) == 1
    assert (
        used_artifacts[0].name
        == "job-source-uncategorized-one_cell_disable_git.ipynb:v0"
    )


def test_notebook_creates_repo_job(notebook):
    with notebook("one_cell_set_git.ipynb") as nb:
        nb.execute_all()
        output = nb.cell_output_html(2)
    # get the run id from the url in the output
    regex_string = r'http:\/\/localhost:\d+\/[^\/]+\/[^\/]+\/runs\/([^\'"]+)'
    run_id = re.search(regex_string, str(output)).group(1)

    api = wandb.Api()
    user = os.environ["WANDB_USERNAME"]
    run = api.run(f"{user}/uncategorized/{run_id}")
    used_artifacts = run.used_artifacts()
    assert len(used_artifacts) == 1
    assert used_artifacts[0].name == "job-test-test_one_cell_set_git.ipynb:v0"
