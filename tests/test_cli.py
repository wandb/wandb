import pytest
import os
import traceback
import click
from wandb import __version__
from wandb import api as wandb_api
from wandb import cli
from wandb import git_repo
from click.testing import CliRunner
from .api_mocks import *
import netrc
import signal
import time
import six
import time
import whaaaaat
import yaml
import git
import webbrowser
import wandb

DUMMY_API_KEY = '1824812581259009ca9981580f8f8a9012409eee'

try:
    # python 3.4+
    from importlib import reload
except ImportError:
    # python 3.2, 3.3
    from imp import reload
except ImportError:
    pass


@pytest.fixture
def runner(monkeypatch):
    monkeypatch.setattr(cli, 'api', wandb_api.Api(
        default_settings={'project': 'test', 'git_tag': True}, load_settings=False))
    monkeypatch.setattr(click, 'launch', lambda x: 1)
    monkeypatch.setattr(whaaaaat, 'prompt', lambda x: {
                        'project_name': 'test_model', 'files': ['weights.h5'],
                        'team_name': 'Manual Entry'})
    monkeypatch.setattr(webbrowser, 'open_new_tab', lambda x: True)
    return CliRunner()


@pytest.fixture
def empty_netrc(monkeypatch):
    class FakeNet(object):
        @property
        def hosts(self):
            return {'api.wandb.ai': None}
    monkeypatch.setattr(netrc, "netrc", lambda *args: FakeNet())


@pytest.fixture
def local_netrc(monkeypatch):
    # TODO: this seems overkill...
    origexpand = os.path.expanduser

    def expand(path):
        return os.path.realpath("netrc") if "netrc" in path else origexpand(path)
    monkeypatch.setattr(os.path, "expanduser", expand)


def git_repo():
    r = git.Repo.init(".")
    open("README", "wb").close()
    r.index.add(["README"])
    r.index.commit("Initial commit")
    return git_repo.GitRepo(lazy=False)


def test_help(runner):
    result = runner.invoke(cli.cli)
    assert result.exit_code == 0
    assert 'Weights & Biases' in result.output
    help_result = runner.invoke(cli.cli, ['--help'])
    assert help_result.exit_code == 0
    assert 'Show this message and exit.' in help_result.output


def test_version(runner):
    result = runner.invoke(cli.cli, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.output


@pytest.mark.skip(reason='config reworked, fixes coming...')
def test_config(runner, monkeypatch):
    with runner.isolated_filesystem():
        result = runner.invoke(cli.config, ["init"])
        print(result.output)
        print(result.exception)
        print(traceback.print_tb(result.exc_info[2]))
        assert "wandb config set" in result.output
        assert os.path.exists("config-defaults.yaml")


@pytest.mark.skip(reason='config reworked, fixes coming...')
def test_config_show(runner, monkeypatch):
    with runner.isolated_filesystem():
        with open("config-defaults.yaml", "w") as f:
            f.write(yaml.dump(
                {'val': {'value': 'awesome', 'desc': 'cool'}, 'bad': {'value': 'shit'}}))
        result_py = runner.invoke(cli.config, ["show"])
        result_yml = runner.invoke(cli.config, ["show", "--format", "yaml"])
        result_json = runner.invoke(cli.config, ["show", "--format", "json"])
        print(result_py.output)
        print(result_py.exception)
        print(traceback.print_tb(result_py.exc_info[2]))
        assert "awesome" in result_py.output
        assert "awesome" in result_yml.output
        assert "awesome" in result_json.output


@pytest.mark.skip(reason='config reworked, fixes coming...')
def test_config_show_empty(runner, monkeypatch):
    with runner.isolated_filesystem():
        result = runner.invoke(cli.config, ["show"])
        print(result.output)
        print(result.exception)
        print(traceback.print_tb(result.exc_info[2]))
        assert "No configuration" in result.output


@pytest.mark.skip(reason='config reworked, fixes coming...')
def test_config_set(runner):
    with runner.isolated_filesystem():
        runner.invoke(cli.config, ["init"])
        result = runner.invoke(cli.config, ["set", "foo=bar"])
        print(result.output)
        print(result.exception)
        print(traceback.print_tb(result.exc_info[2]))
        assert "foo='bar'" in result.output


@pytest.mark.skip(reason='config reworked, fixes coming...')
def test_config_del(runner):
    with runner.isolated_filesystem():
        with open("config-defaults.yaml", "w") as f:
            f.write(yaml.dump(
                {'val': {'value': 'awesome', 'desc': 'cool'}, 'bad': {'value': 'shit'}}))
        result = runner.invoke(cli.config, ["del", "bad"])
        print(result.output)
        print(result.exception)
        print(traceback.print_tb(result.exc_info[2]))
        assert "1 parameters changed" in result.output


@pytest.mark.skip(reason='feature disabled')
def test_push(runner, request_mocker, query_project, upload_url, upsert_run, monkeypatch):
    query_project(request_mocker)
    upload_url(request_mocker)
    update_mock = upsert_run(request_mocker)
    with runner.isolated_filesystem():
        # So GitRepo is in this cwd
        os.mkdir('wandb')
        monkeypatch.setattr(cli, 'api', wandb_api.Api({'project': 'test'}))
        with open("wandb/latest.yaml", "w") as f:
            f.write(yaml.dump({'wandb_version': 1, 'test': {
                    'value': 'success', 'desc': 'My life'}}))
        with open('weights.h5', 'wb') as f:
            f.write(os.urandom(5000))
        result = runner.invoke(
            cli.push, ['test/default', 'weights.h5', '-m', 'My description'])
        print(result.output)
        print(result.exception)
        print(traceback.print_tb(result.exc_info[2]))
        assert result.exit_code == 0
        assert "Updating run: test/default" in result.output


@pytest.mark.skip(reason='feature disabled')
def test_push_no_run(runner):
    with runner.isolated_filesystem():
        with open('weights.h5', 'wb') as f:
            f.write(os.urandom(5000))
        result = runner.invoke(
            cli.push, ['weights.h5', '-p', 'test', '-m', 'Something great'])
        print(result.output)
        print(result.exception)
        print(traceback.print_tb(result.exc_info[2]))
        assert result.exit_code == 2
        assert "Run id is required if files are specified." in result.output


@pytest.mark.skip(reason='feature disabled')
def test_push_dirty_git(runner, monkeypatch):
    with runner.isolated_filesystem():
        os.mkdir('wandb')

        # If the test was run from a directory containing .wandb, then __stage_dir__
        # was '.wandb' when imported by api.py, reload to fix. UGH!
        reload(wandb)
        repo = git_repo()
        open("foo.txt", "wb").close()
        repo.repo.index.add(["foo.txt"])
        monkeypatch.setattr(cli, 'api', wandb_api.Api({'project': 'test'}))
        cli.api._settings['git_tag'] = True
        result = runner.invoke(
            cli.push, ["test", "foo.txt", "-p", "test", "-m", "Dirty"])
        print(result.output)
        print(result.exception)
        print(traceback.print_tb(result.exc_info[2]))
        assert result.exit_code == 1
        assert "You have un-committed changes." in result.output


@pytest.mark.skip(reason='feature disabled')
def test_push_dirty_force_git(runner, request_mocker, query_project, upload_url, upsert_run, monkeypatch):
    query_project(request_mocker)
    upload_url(request_mocker)
    update_mock = upsert_run(request_mocker)
    with runner.isolated_filesystem():
        # So GitRepo is in this cwd
        monkeypatch.setattr(cli, 'api', wandb_api.Api({'project': 'test'}))
        repo = git_repo()
        with open('weights.h5', 'wb') as f:
            f.write(os.urandom(100))
        repo.repo.index.add(["weights.h5"])
        result = runner.invoke(
            cli.push, ["test", "weights.h5", "-f", "-p", "test", "-m", "Dirty"])
        print(result.output)
        print(result.exception)
        print(traceback.print_tb(result.exc_info[2]))
        assert result.exit_code == 0


@pytest.mark.skip(reason='feature disabled')
def test_pull(runner, request_mocker, query_project, download_url):
    query_project(request_mocker)
    download_url(request_mocker)
    with runner.isolated_filesystem():
        result = runner.invoke(cli.pull, ['test', '--project', 'test'])

        print(result.output)
        print(result.exception)
        print(traceback.print_tb(result.exc_info[2]))
        assert result.exit_code == 0
        assert "Downloading: test/test" in result.output
        assert os.path.isfile("weights.h5")
        assert "File model.json" in result.output
        assert "File weights.h5" in result.output


@pytest.mark.skip(reason='feature disabled')
def test_pull_custom_run(runner, request_mocker, query_project, download_url):
    query_project(request_mocker)
    download_url(request_mocker)
    with runner.isolated_filesystem():
        result = runner.invoke(cli.pull, ['test/test'])

        print(result.output)
        print(result.exception)
        print(traceback.print_tb(result.exc_info[2]))
        assert result.exit_code == 0
        assert "Downloading: test/test" in result.output


@pytest.mark.skip(reason='feature disabled')
def test_pull_empty_run(runner, request_mocker, query_empty_project, download_url):
    query_empty_project(request_mocker)
    result = runner.invoke(cli.pull, ['test/test'])

    print(result.output)
    print(result.exception)
    print(traceback.print_tb(result.exc_info[2]))
    assert result.exit_code == 1
    assert "Run has no files" in result.output


def test_projects(runner, request_mocker, query_projects):
    query_projects(request_mocker)
    result = runner.invoke(cli.projects)
    assert result.exit_code == 0
    assert "test_2 - Test model" in result.output


@pytest.mark.skip(reason='feature disabled')
def test_status(runner, request_mocker, query_project):
    with runner.isolated_filesystem():
        query_project(request_mocker)
        result = runner.invoke(cli.status, ["-p", "foo"])
        print(result.output)
        print(result.exception)
        print(traceback.print_tb(result.exc_info[2]))
        assert result.exit_code == 0
        assert "/latest" in result.output


@pytest.mark.skip(reason='feature disabled')
def test_status_project_and_run(runner, request_mocker, query_project):
    query_project(request_mocker)
    result = runner.invoke(cli.status, ["test/awesome"])
    print(result.output)
    print(result.exception)
    print(traceback.print_tb(result.exc_info[2]))
    assert result.exit_code == 0
    assert "test/awesome" in result.output


def test_no_project_bad_command(runner):
    result = runner.invoke(cli.cli, ["fsd"])
    print(result.output)
    print(result.exception)
    print(traceback.print_tb(result.exc_info[2]))
    assert "No such command" in result.output
    assert result.exit_code == 2


@pytest.mark.skip('restore functionality broken for now, fixes coming...')
def test_restore(runner, request_mocker, query_run, monkeypatch):
    mock = query_run(request_mocker)
    with runner.isolated_filesystem():
        os.mkdir("wandb")
        repo = git_repo()
        with open("patch.txt", "w") as f:
            f.write("test")
        repo.repo.index.add(["patch.txt"])
        repo.repo.commit()
        monkeypatch.setattr(cli, 'api', wandb_api.Api({'project': 'test'}))
        result = runner.invoke(cli.restore, ["test/abcdef"])
        print(result.output)
        print(traceback.print_tb(result.exc_info[2]))
        assert result.exit_code == 0
        assert "Created branch wandb/abcdef" in result.output
        assert "Applied patch" in result.output
        assert "Restored config variables" in result.output


def test_projects_error(runner, request_mocker, query_projects):
    query_projects(request_mocker, status_code=400)
    result = runner.invoke(cli.projects)
    assert result.exit_code == 1
    print(result.output)
    assert "Error" in result.output


def test_init_new_login(runner, empty_netrc, local_netrc, request_mocker, query_projects, query_viewer):
    mock = query_projects(request_mocker)
    query_viewer(request_mocker)
    with runner.isolated_filesystem():
        # If the test was run from a directory containing .wandb, then __stage_dir__
        # was '.wandb' when imported by api.py, reload to fix. UGH!
        reload(wandb)
        result = runner.invoke(cli.init, input="%s\nvanpelt" % DUMMY_API_KEY)
        print('Output: ', result.output)
        print('Exception: ', result.exception)
        print('Traceback: ', traceback.print_tb(result.exc_info[2]))
        assert mock.called
        assert result.exit_code == 0
        with open("netrc", "r") as f:
            generatedNetrc = f.read()
        with open("wandb/settings", "r") as f:
            generatedWandb = f.read()
        assert DUMMY_API_KEY in generatedNetrc
        assert "test_model" in generatedWandb


@pytest.mark.teams("foo", "bar")
def test_init_multi_team(runner, empty_netrc, local_netrc, request_mocker, query_projects, query_viewer):
    mock = query_projects(request_mocker)
    query_viewer(request_mocker)
    with runner.isolated_filesystem():
        # If the test was run from a directory containing .wandb, then __stage_dir__
        # was '.wandb' when imported by api.py, reload to fix. UGH!
        reload(wandb)
        result = runner.invoke(
            cli.init, input="%s\nvanpelt" % DUMMY_API_KEY)
        print('Output: ', result.output)
        print('Exception: ', result.exception)
        print('Traceback: ', traceback.print_tb(result.exc_info[2]))
        assert mock.called
        assert result.exit_code == 0
        with open("netrc", "r") as f:
            generatedNetrc = f.read()
        with open("wandb/settings", "r") as f:
            generatedWandb = f.read()
        assert DUMMY_API_KEY in generatedNetrc
        assert "test_model" in generatedWandb


def test_init_reinit(runner, empty_netrc, local_netrc, request_mocker, query_projects, query_viewer):
    query_viewer(request_mocker)
    query_projects(request_mocker)
    with runner.isolated_filesystem():
        os.mkdir('wandb')
        result = runner.invoke(
            cli.init, input="y\n%s\nvanpelt\n" % DUMMY_API_KEY)
        print(result.output)
        print(result.exception)
        print(traceback.print_tb(result.exc_info[2]))
        assert result.exit_code == 0
        with open("netrc", "r") as f:
            generatedNetrc = f.read()
        with open("wandb/settings", "r") as f:
            generatedWandb = f.read()
        assert DUMMY_API_KEY in generatedNetrc
        assert "test_model" in generatedWandb


def test_init_add_login(runner, empty_netrc, local_netrc, request_mocker, query_projects, query_viewer):
    query_viewer(request_mocker)
    query_projects(request_mocker)
    with runner.isolated_filesystem():
        with open("netrc", "w") as f:
            f.write("previous config")
        result = runner.invoke(cli.init, input="%s\nvanpelt\n" % DUMMY_API_KEY)
        print(result.output)
        print(result.exception)
        print(traceback.print_tb(result.exc_info[2]))
        assert result.exit_code == 0
        with open("netrc", "r") as f:
            generatedNetrc = f.read()
        with open("wandb/settings", "r") as f:
            generatedWandb = f.read()
        assert DUMMY_API_KEY in generatedNetrc
        assert "previous config" in generatedNetrc


def test_init_existing_login(runner, local_netrc, request_mocker, query_projects, query_viewer):
    query_viewer(request_mocker)
    query_projects(request_mocker)
    with runner.isolated_filesystem():
        with open("netrc", "w") as f:
            f.write("machine api.wandb.ai\n\ttest\t12345")
        result = runner.invoke(cli.init, input="vanpelt\n")
        print(result.output)
        print(result.exception)
        print(traceback.print_tb(result.exc_info[2]))
        assert result.exit_code == 0
        with open("wandb/settings", "r") as f:
            generatedWandb = f.read()
        assert "test_model" in generatedWandb
        assert "This directory is configured" in result.output
