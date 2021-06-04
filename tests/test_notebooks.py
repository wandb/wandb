import os
import platform
import subprocess
import pytest
import json
import sys
import wandb
import pickle

from wandb.errors import UsageError

pytestmark = pytest.mark.skipif(
    sys.version_info < (3, 5) or platform.system() == "Windows",
    reason="Our notebook fixture only works in py3, windows was flaking",
)


def test_one_cell(notebook):
    with notebook("one_cell.ipynb") as nb:
        nb.execute_all()
        output = nb.cell_output(0)
        print(output)
        assert "lovely-dawn-32" in output[-1]["data"]["text/html"]
        # assert "Failed to query for notebook name" not in text


def test_magic(notebook):
    with notebook("magic.ipynb") as nb:
        nb.execute_all()
        output = nb.cell_output(1)
        print(output)
        assert notebook.base_url in output[0]["data"]["text/html"]


def test_code_saving(notebook, live_mock_server):
    # TODO: this is awfully slow, we should likely run these in parallel
    with notebook("code_saving.ipynb") as nb:
        nb.execute_all()
        server_ctx = live_mock_server.get_ctx()
        artifact_name = list(server_ctx["artifacts"].keys())[0]
        # We run 3 cells after calling wandb.init
        assert len(server_ctx["artifacts"][artifact_name]) == 3

    with notebook("code_saving.ipynb", save_code=False) as nb:
        nb.execute_all()
        assert "Failed to detect the name of this notebook" in nb.all_output_text()

    # Let's make sure we warn the user if they lie to us.
    with notebook("code_saving.ipynb") as nb:
        os.remove("code_saving.ipynb")
        nb.execute_all()
        assert "WANDB_NOTEBOOK_NAME should be a path" in nb.all_output_text()


def test_notebook_not_exists(mocked_ipython, live_mock_server, capsys, test_settings):
    os.environ["WANDB_NOTEBOOK_NAME"] = "fake.ipynb"
    wandb.init(settings=test_settings)
    _, err = capsys.readouterr()
    assert "WANDB_NOTEBOOK_NAME should be a path" in err
    del os.environ["WANDB_NOTEBOOK_NAME"]


def test_notebook_metadata_jupyter(mocker, mocked_module, live_mock_server):
    ipyconnect = mocker.patch("ipykernel.connect")
    ipyconnect.get_connection_file.return_value = "kernel-12345.json"
    serverapp = mocked_module("jupyter_server.serverapp")
    serverapp.list_running_servers.return_value = [
        {"url": live_mock_server.base_url, "notebook_dir": "/test"}
    ]
    meta = wandb.jupyter.notebook_metadata(False)
    assert meta == {"path": "test.ipynb", "root": "/test", "name": "test.ipynb"}


def test_notebook_metadata_no_servers(mocker, mocked_module):
    ipyconnect = mocker.patch("ipykernel.connect")
    ipyconnect.get_connection_file.return_value = "kernel-12345.json"
    serverapp = mocked_module("jupyter_server.serverapp")
    serverapp.list_running_servers.return_value = []
    meta = wandb.jupyter.notebook_metadata(False)
    assert meta == {}


def test_notebook_metadata_colab(mocked_module):
    colab = mocked_module("google.colab")
    colab._message.blocking_request.return_value = {
        "ipynb": {"metadata": {"colab": {"name": "colab.ipynb"}}}
    }
    meta = wandb.jupyter.notebook_metadata(False)
    assert meta == {
        "root": "/content",
        "path": "colab.ipynb",
        "name": "colab.ipynb",
    }


def test_notebook_metadata_kaggle(mocker, mocked_module):
    os.environ["KAGGLE_KERNEL_RUN_TYPE"] = "test"
    kaggle = mocked_module("kaggle_session")
    kaggle_client = mocker.MagicMock()
    kaggle_client.get_exportable_ipynb.return_value = {
        "source": json.dumps({"metadata": {}, "cells": []})
    }
    kaggle.UserSessionClient.return_value = kaggle_client
    meta = wandb.jupyter.notebook_metadata(False)
    assert meta == {
        "root": "/kaggle/working",
        "path": "kaggle.ipynb",
        "name": "kaggle.ipynb",
    }


def test_databricks_notebook_doesnt_hang_on_wandb_login(mocked_module):
    # test for WB-5264

    # make the test think we are running in a databricks notebook
    dbutils = mocked_module("dbutils")
    dbutils.shell.sc.appName = "Databricks Shell"

    # when we try to call wandb.login(), should fail with no-tty
    with pytest.raises(UsageError, match="tty"):
        wandb.login()


def test_notebook_exits(live_mock_server, test_settings):

    script_dirname = os.path.dirname(__file__)
    script_fname = os.path.join(script_dirname, "notebooks/ipython_exit.py")
    bindir = os.path.dirname(sys.executable)
    ipython = os.path.join(bindir, "ipython")
    cmd = [ipython, script_fname]

    subprocess.check_call(cmd)
