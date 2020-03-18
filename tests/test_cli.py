import contextlib
import datetime
import pytest
import os
import traceback
import click
from wandb import __version__
from wandb.apis import InternalApi
from wandb import cli, env
from wandb import util
from .utils import runner, git_repo
from .api_mocks import *
import netrc
import signal
import time
import six
import time
import yaml
import git
import re
import shutil
import webbrowser
import wandb
import threading
import subprocess
import platform

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
def empty_netrc(monkeypatch):
    class FakeNet(object):
        @property
        def hosts(self):
            return {'api.wandb.ai': None}
    monkeypatch.setattr(netrc, "netrc", lambda *args: FakeNet())


@contextlib.contextmanager
def config_dir():
    try:
        os.environ["WANDB_CONFIG"] = os.getcwd()
        yield
    finally:
        del os.environ["WANDB_CONFIG"]

def setup_module(module):
    os.environ["WANDB_TEST"] = "true"


def teardown_module(module):
    del os.environ["WANDB_TEST"]


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


def test_status(runner, request_mocker, query_project):
    with runner.isolated_filesystem():
        os.mkdir("wandb")
        query_project(request_mocker)
        result = runner.invoke(cli.status)
        print(result.output)
        print(result.exception)
        print(traceback.print_tb(result.exc_info[2]))
        assert result.exit_code == 0
        assert "latest" in result.output


@pytest.mark.skip(reason='currently we dont parse entity/project')
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


def test_restore_no_remote(runner, request_mocker, query_run, git_repo, docker, monkeypatch):
    # git_repo creates it's own isolated filesystem
    mock = query_run(request_mocker)
    with open("patch.txt", "w") as f:
        f.write("test")
    git_repo.repo.index.add(["patch.txt"])
    git_repo.repo.commit()
    monkeypatch.setattr(cli, 'api', InternalApi({'project': 'test'}))
    result = runner.invoke(cli.restore, ["wandb/test:abcdef"])
    print(result.output)
    print(traceback.print_tb(result.exc_info[2]))
    assert result.exit_code == 0
    assert "Created branch wandb/abcdef" in result.output
    assert "Applied patch" in result.output
    assert "Restored config variables to wandb" + os.sep in result.output
    assert "Launching docker container" in result.output
    docker.assert_called_with(['docker', 'run', '-e', 'LANG=C.UTF-8', '-e', 'WANDB_DOCKER=wandb/deepo@sha256:abc123', '--ipc=host', '-v',
    wandb.docker.entrypoint+':/wandb-entrypoint.sh', '--entrypoint', '/wandb-entrypoint.sh', '-v', os.getcwd()+':/app', '-w', '/app', '-e',
    'WANDB_API_KEY=test', '-e', 'WANDB_COMMAND=python train.py --test foo', '-it', 'test/docker', '/bin/bash'])

def test_restore_bad_remote(runner, request_mocker, query_run, git_repo, docker, monkeypatch):
    # git_repo creates it's own isolated filesystem
    mock = query_run(request_mocker, {"git": {"repo": "http://fake.git/foo/bar"}})
    api = InternalApi({'project': 'test'})
    monkeypatch.setattr(cli, 'api', api)
    def bad_commit(cmt):
        raise ValueError()
    monkeypatch.setattr(api.git.repo, 'commit', bad_commit)
    monkeypatch.setattr(api, "download_urls", lambda *args, **kwargs: []) 
    result = runner.invoke(cli.restore, ["wandb/test:abcdef"])
    print(result.output)
    print(traceback.print_tb(result.exc_info[2]))
    assert result.exit_code == 1
    assert "Run `git clone http://fake.git/foo/bar`" in result.output

def test_restore_good_remote(runner, request_mocker, query_run, git_repo, docker, monkeypatch):
    # git_repo creates it's own isolated filesystem
    git_repo.repo.create_remote('origin', "git@fake.git:foo/bar")
    monkeypatch.setattr(subprocess, 'check_call', lambda command: True)
    mock = query_run(request_mocker, {"git": {"repo": "http://fake.git/foo/bar"}})
    monkeypatch.setattr(cli, 'api', InternalApi({'project': 'test'}))
    result = runner.invoke(cli.restore, ["wandb/test:abcdef"])
    print(result.output)
    print(traceback.print_tb(result.exc_info[2]))
    assert result.exit_code == 0
    assert "Created branch wandb/abcdef" in result.output

def test_restore_no_git(runner, request_mocker, query_run, git_repo, docker, monkeypatch):
    # git_repo creates it's own isolated filesystem
    mock = query_run(request_mocker, {"git": {"repo": "http://fake.git/foo/bar"}})
    monkeypatch.setattr(cli, 'api', InternalApi({'project': 'test'}))
    result = runner.invoke(cli.restore, ["wandb/test:abcdef", "--no-git"])
    print(result.output)
    print(traceback.print_tb(result.exc_info[2]))
    assert result.exit_code == 0
    assert "Restored config variables" in result.output

def test_restore_slashes(runner, request_mocker, query_run, git_repo, docker, monkeypatch):
    # git_repo creates it's own isolated filesystem
    mock = query_run(request_mocker, {"git": {"repo": "http://fake.git/foo/bar"}})
    monkeypatch.setattr(cli, 'api', InternalApi({'project': 'test'}))
    result = runner.invoke(cli.restore, ["wandb/test/abcdef", "--no-git"])
    print(result.output)
    print(traceback.print_tb(result.exc_info[2]))
    assert result.exit_code == 0
    assert "Restored config variables" in result.output

def test_restore_no_entity(runner, request_mocker, query_run, git_repo, docker, monkeypatch):
    # git_repo creates it's own isolated filesystem
    mock = query_run(request_mocker, {"git": {"repo": "http://fake.git/foo/bar"}})
    monkeypatch.setattr(cli, 'api', InternalApi({'project': 'test'}))
    result = runner.invoke(cli.restore, ["test/abcdef", "--no-git"])
    print(result.output)
    print(traceback.print_tb(result.exc_info[2]))
    assert result.exit_code == 0
    assert "Restored config variables" in result.output

def test_restore_not_git(runner, request_mocker, query_run, docker, monkeypatch):
    # git_repo creates it's own isolated filesystem
    with runner.isolated_filesystem():
        mock = query_run(request_mocker)
        monkeypatch.setattr(cli, 'api', InternalApi({'project': 'test'}))
        result = runner.invoke(cli.restore, ["test/abcdef"])
        print(result.output)
        print(traceback.print_tb(result.exc_info[2]))
        assert result.exit_code == 0
        assert "Original run has no git history" in result.output

@pytest.fixture
def docker(request_mocker, query_run, mocker, monkeypatch):
    mock = query_run(request_mocker)
    docker = mocker.MagicMock()
    api_key = mocker.patch('wandb.apis.InternalApi.api_key', new_callable=mocker.PropertyMock)
    api_key.return_value = "test"
    api = InternalApi({'project': 'test'})
    monkeypatch.setattr(cli, 'find_executable', lambda name: True)
    monkeypatch.setattr(cli, 'api', api)
    old_call = subprocess.call
    def new_call(command, **kwargs):
        if command[0] == "docker":
            return docker(command)
        else:
            return old_call(command, **kwargs)
    monkeypatch.setattr(subprocess, 'call', new_call)
    monkeypatch.setattr(subprocess, 'check_output',
                        lambda *args, **kwargs: b"wandb/deepo@sha256:abc123")
    return docker

@pytest.fixture
def no_tty(mocker):
    with mocker.patch("wandb.sys.stdin") as stdin_mock:
        stdin_mock.isatty.return_value = False
        yield

def test_docker_run_digest(runner, docker, monkeypatch):
    runner.invoke(cli.docker_run, ["wandb/deepo@sha256:3ddd2547d83a056804cac6aac48d46c5394a76df76b672539c4d2476eba38177"])
    docker.assert_called_once_with(['docker', 'run', '-e', 'WANDB_API_KEY=test', '-e', 'WANDB_DOCKER=wandb/deepo@sha256:3ddd2547d83a056804cac6aac48d46c5394a76df76b672539c4d2476eba38177', '--runtime', 'nvidia', 'wandb/deepo@sha256:3ddd2547d83a056804cac6aac48d46c5394a76df76b672539c4d2476eba38177'])

def test_docker_run_bad_image(runner, docker, monkeypatch):
    runner.invoke(cli.docker_run, ["wandb///foo$"])
    docker.assert_called_once_with(['docker', 'run', '-e', 'WANDB_API_KEY=test', '--runtime', 'nvidia', "wandb///foo$"])

def test_docker_run_no_nvidia(runner, docker, monkeypatch):
    monkeypatch.setattr(cli, 'find_executable', lambda name: False)
    runner.invoke(cli.docker_run, ["run", "-v", "cool:/cool", "rad"])
    docker.assert_called_once_with(['docker', 'run', '-e', 'WANDB_API_KEY=test', '-e', 'WANDB_DOCKER=wandb/deepo@sha256:abc123', '-v', 'cool:/cool', 'rad'])

def test_docker_run_nvidia(runner, docker):
    runner.invoke(cli.docker_run, ["run", "-v", "cool:/cool", "rad", "/bin/bash", "cool"])
    docker.assert_called_once_with(['docker', 'run', '-e', 'WANDB_API_KEY=test', '-e', 'WANDB_DOCKER=wandb/deepo@sha256:abc123', 
        '--runtime', 'nvidia', '-v', 'cool:/cool', 'rad', '/bin/bash', 'cool'])

def test_docker(runner, docker):
    with runner.isolated_filesystem():
        result = runner.invoke(cli.docker, ["test"])
        print(result.output)
        print(traceback.print_tb(result.exc_info[2]))
        docker.assert_called_once_with(['docker', 'run', '-e', 'LANG=C.UTF-8', '-e', 'WANDB_DOCKER=wandb/deepo@sha256:abc123', '--ipc=host', '-v', 
            wandb.docker.entrypoint+':/wandb-entrypoint.sh', '--entrypoint', '/wandb-entrypoint.sh', '-v', 
            os.getcwd()+':/app', '-w', '/app', '-e', 'WANDB_API_KEY=test', '-it', 'test', '/bin/bash'])
        assert result.exit_code == 0

def test_docker_basic(runner, docker, git_repo):
    result = runner.invoke(cli.docker, ["test:abc123"])
    print(result.output)
    print(traceback.print_tb(result.exc_info[2]))
    assert "Launching docker container" in result.output
    docker.assert_called_once_with(['docker', 'run', '-e', 'LANG=C.UTF-8', '-e', 'WANDB_DOCKER=wandb/deepo@sha256:abc123', '--ipc=host', '-v', 
            wandb.docker.entrypoint+':/wandb-entrypoint.sh', '--entrypoint', '/wandb-entrypoint.sh', '-v', 
            os.getcwd()+':/app', '-w', '/app', '-e', 'WANDB_API_KEY=test', '-it', 'test:abc123', '/bin/bash'])
    assert result.exit_code == 0

def test_docker_sha(runner, docker):
    result = runner.invoke(cli.docker, ["test@sha256:abc123"])
    print(result.output)
    print(traceback.print_tb(result.exc_info[2]))
    docker.assert_called_once_with(['docker', 'run', '-e', 'LANG=C.UTF-8', '-e', 'WANDB_DOCKER=test@sha256:abc123', '--ipc=host', '-v',
    wandb.docker.entrypoint+':/wandb-entrypoint.sh', '--entrypoint', '/wandb-entrypoint.sh', '-v', os.getcwd()+':/app', '-w', '/app', '-e',
    'WANDB_API_KEY=test', '-it', 'test@sha256:abc123', '/bin/bash'])
    assert result.exit_code == 0

def test_docker_no_dir(runner, docker):
    result = runner.invoke(cli.docker, ["test:abc123", "--no-dir"])
    print(result.output)
    print(traceback.print_tb(result.exc_info[2]))
    docker.assert_called_once_with(['docker', 'run', '-e', 'LANG=C.UTF-8', '-e', 'WANDB_DOCKER=wandb/deepo@sha256:abc123', '--ipc=host', '-v', 
        wandb.docker.entrypoint+':/wandb-entrypoint.sh', '--entrypoint', '/wandb-entrypoint.sh', '-e', 'WANDB_API_KEY=test', '-it', 'test:abc123', '/bin/bash'])
    assert result.exit_code == 0

def test_docker_no_interactive_custom_command(runner, docker, git_repo):
    result = runner.invoke(cli.docker, ["test:abc123", "--no-tty", "--cmd", "python foo.py"])
    print(result.output)
    print(traceback.print_tb(result.exc_info[2]))
    
    docker.assert_called_once_with(['docker', 'run', '-e', 'LANG=C.UTF-8', '-e', 'WANDB_DOCKER=wandb/deepo@sha256:abc123', '--ipc=host', '-v', wandb.docker.entrypoint+':/wandb-entrypoint.sh', 
    '--entrypoint', '/wandb-entrypoint.sh', '-v', os.getcwd()+':/app', '-w', '/app', '-e', 'WANDB_API_KEY=test', 'test:abc123', '/bin/bash', '-c', 'python foo.py'])
    assert result.exit_code == 0


def test_docker_jupyter(runner, docker):
    with runner.isolated_filesystem():
        result = runner.invoke(cli.docker, ["test", "--jupyter"])
        print(result.output)
        print(traceback.print_tb(result.exc_info[2]))
        
        docker.assert_called_once_with(['docker', 'run', '-e', 'LANG=C.UTF-8', '-e', 'WANDB_DOCKER=wandb/deepo@sha256:abc123', '--ipc=host', '-v', wandb.docker.entrypoint+':/wandb-entrypoint.sh', 
        '--entrypoint', '/wandb-entrypoint.sh', '-v', os.getcwd()+':/app', '-w', '/app', '-e', 'WANDB_API_KEY=test', '-e', 'WANDB_ENSURE_JUPYTER=1', '-p', '8888:8888', 
        'test', '/bin/bash', '-c', 'jupyter lab --no-browser --ip=0.0.0.0 --allow-root --NotebookApp.token= --notebook-dir /app'])
        assert result.exit_code == 0

def test_docker_args(runner, docker):
    with runner.isolated_filesystem():
        result = runner.invoke(cli.docker, ["test", "-v", "/tmp:/tmp"])
        print(result.output)
        print(traceback.print_tb(result.exc_info[2]))
        docker.assert_called_with(['docker', 'run', '-e', 'LANG=C.UTF-8', '-e', 'WANDB_DOCKER=wandb/deepo@sha256:abc123', '--ipc=host', '-v', wandb.docker.entrypoint+':/wandb-entrypoint.sh',
        '--entrypoint', '/wandb-entrypoint.sh', '-v', os.getcwd()+':/app', '-w', '/app', '-e', 'WANDB_API_KEY=test', 'test', '-v', '/tmp:/tmp', '-it', 'wandb/deepo:all-cpu', '/bin/bash'])
        assert result.exit_code == 0

def test_docker_digest(runner, docker):
    with runner.isolated_filesystem():
        result = runner.invoke(cli.docker, ["test", "--digest"])
        print(result.output)
        print(traceback.print_tb(result.exc_info[2]))
        assert result.output == "wandb/deepo@sha256:abc123"
        assert result.exit_code == 0


def test_projects_error(runner, request_mocker, query_projects):
    query_projects(request_mocker, status_code=400)
    # Ugly, reach in to APIs request Retry object and tell it to only
    # retry for 50us
    cli.api.gql._retry_timedelta = datetime.timedelta(0, 0, 50)
    result = runner.invoke(cli.projects)
    print(result.exception)
    print(result.output)
    print(traceback.print_tb(result.exc_info[2]))
    assert result.exit_code == 1
    assert "Error" in result.output


def test_login_key_arg(runner, empty_netrc, local_netrc):
    with runner.isolated_filesystem():
        # If the test was run from a directory containing .wandb, then __stage_dir__
        # was '.wandb' when imported by api.py, reload to fix. UGH!
        reload(wandb)
        result = runner.invoke(cli.login, [DUMMY_API_KEY])
        print('Output: ', result.output)
        print('Exception: ', result.exception)
        print('Traceback: ', traceback.print_tb(result.exc_info[2]))
        assert result.exit_code == 0
        with open("netrc", "r") as f:
            generatedNetrc = f.read()
        assert DUMMY_API_KEY in generatedNetrc


def test_login_anonymously(runner, monkeypatch, empty_netrc, local_netrc):
    with runner.isolated_filesystem():
        api = InternalApi()
        monkeypatch.setattr(cli, 'api', api)
        monkeypatch.setattr(api, 'create_anonymous_api_key', lambda *args, **kwargs: DUMMY_API_KEY)
        result = runner.invoke(cli.login, ['--anonymously'])
        print('Output: ', result.output)
        print('Exception: ', result.exception)
        print('Traceback: ', traceback.print_tb(result.exc_info[2]))
        assert result.exit_code == 0
        with open("netrc", "r") as f:
            generated_netrc = f.read()
        assert DUMMY_API_KEY in generated_netrc


def test_login_abort(runner, empty_netrc, local_netrc, mocker, monkeypatch):
    with runner.isolated_filesystem():
        reload(wandb)
        def prompt(*args, **kwargs):
            raise click.exceptions.Abort()
        mocker.patch("click.prompt", prompt)
        result = runner.invoke(cli.login)
        print('Output: ', result.output)
        print('Exception: ', result.exception)
        print('Traceback: ', traceback.print_tb(result.exc_info[2]))
        assert result.exit_code == 0
        assert "Disabling Weights & Biases. Run 'wandb login' again to re-enable" in result.output


def test_signup(runner, empty_netrc, local_netrc, mocker, monkeypatch):
    with runner.isolated_filesystem():
        # If the test was run from a directory containing .wandb, then __stage_dir__
        # was '.wandb' when imported by api.py, reload to fix. UGH!
        reload(wandb)
        def prompt(*args, **kwargs):
            #raise click.exceptions.Abort()
            return DUMMY_API_KEY
        mocker.patch("wandb.util.prompt_api_key", prompt)
        result = runner.invoke(cli.login)
        print('Output: ', result.output)
        print('Exception: ', result.exception)
        print('Traceback: ', traceback.print_tb(result.exc_info[2]))
        assert result.exit_code == 0
        assert "Successfully logged in to Weights & Biases!" in result.output


def test_init_new_login_no_browser(runner, empty_netrc, local_netrc, request_mocker, query_projects, query_viewer, monkeypatch):
    mock = query_projects(request_mocker)
    query_viewer(request_mocker)
    monkeypatch.setattr(webbrowser, 'open_new_tab', lambda x: False)
    with runner.isolated_filesystem():
        # If the test was run from a directory containing .wandb, then __stage_dir__
        # was '.wandb' when imported by api.py, reload to fix. UGH!
        reload(wandb)
        login_result = runner.invoke(cli.login, [DUMMY_API_KEY])
        init_result = runner.invoke(cli.init, input="y\n\n\n")
        print('Output: ', init_result.output)
        print('Exception: ', init_result.exception)
        print('Traceback: ', traceback.print_tb(init_result.exc_info[2]))
        assert mock.called
        assert login_result.exit_code == 0
        assert init_result.exit_code == 0
        with open("netrc", "r") as f:
            generatedNetrc = f.read()
        with open("wandb/settings", "r") as f:
            generatedWandb = f.read()
        assert DUMMY_API_KEY in generatedNetrc
        assert "test_model" in generatedWandb
        assert "Successfully logged in" in login_result.output
        assert "This directory is configured!" in init_result.output


@pytest.mark.teams("foo", "bar")
def test_init_multi_team(runner, empty_netrc, local_netrc, request_mocker, query_projects, query_viewer):
    mock = query_projects(request_mocker)
    query_viewer(request_mocker)
    with runner.isolated_filesystem():
        # If the test was run from a directory containing .wandb, then __stage_dir__
        # was '.wandb' when imported by api.py, reload to fix. UGH!
        reload(wandb)
        login_result = runner.invoke(cli.login, [DUMMY_API_KEY])
        init_result = runner.invoke(cli.init, input="y\nvanpelt\n")
        print('Output: ', init_result.output)
        print('Exception: ', init_result.exception)
        print('Traceback: ', traceback.print_tb(init_result.exc_info[2]))
        assert mock.called
        assert login_result.exit_code == 0
        assert init_result.exit_code == 0
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
        runner.invoke(cli.login, [DUMMY_API_KEY])
        result = runner.invoke(cli.init, input="y\nvanpelt\n")
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
        with config_dir():
            with open("netrc", "w") as f:
                f.write("previous config")
            runner.invoke(cli.login, [DUMMY_API_KEY])
            result = runner.invoke(cli.init, input="y\n%s\nvanpelt\n" % DUMMY_API_KEY)
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
            f.write("machine api.wandb.ai\n\tlogin test\tpassword 12345")
        result = runner.invoke(cli.init, input="vanpelt\n")
        print(result.output)
        print(result.exception)
        print(traceback.print_tb(result.exc_info[2]))
        assert result.exit_code == 0
        with open("wandb/settings", "r") as f:
            generatedWandb = f.read()
        assert "test_model" in generatedWandb
        assert "This directory is configured" in result.output


def test_run_with_error(runner, request_mocker, upsert_run, git_repo, query_viewer, no_tty):
    upsert_run(request_mocker)
    query_viewer(request_mocker)

    runner.invoke(cli.off)
    result = runner.invoke(cli.run, ["python", "missing.py"])

    print(result.output)
    print(result.exception)
    print(traceback.print_tb(result.exc_info[2]))
    output = result.output.encode("utf8")
    assert "not found" in str(output) or "No such file" in str(output)
    # TODO: there's a race between the sigint and the actual failure so exit_code could be 1 or 255
    assert result.exit_code > 0


@pytest.mark.updateAvailable(True)
def test_run_update(runner, request_mocker, upsert_run, git_repo, upload_logs):
    upload_logs(request_mocker, "abc123")
    upsert_run(request_mocker)
    runner.invoke(cli.off)
    with open("simple.py", "w") as f:
        f.write('print("Done!")')
    result = runner.invoke(cli.run, ["--id=abc123", "--", "simple.py"])
    print(result.output)
    print(result.exception)
    print(traceback.print_tb(result.exc_info[2]))


def test_enable_on(runner, git_repo):
    with open("wandb/settings", "w") as f:
        f.write("[default]\nproject=rad")
    result = runner.invoke(cli.on)
    print(result.output)
    print(result.exception)
    print(traceback.print_tb(result.exc_info[2]))
    assert "W&B enabled" in str(result.output)


def test_enable_off(runner, git_repo):
    with open("wandb/settings", "w") as f:
        f.write("[default]\nproject=rad")
    result = runner.invoke(cli.off)
    print(result.output)
    print(result.exception)
    print(traceback.print_tb(result.exc_info[2]))
    assert "W&B disabled" in str(result.output)
    assert "disabled" in open("wandb/settings").read()


def test_sync(runner, git_repo, mock_server):
    # Un comment this line when re-recording the cassette
    os.environ['WANDB_API_KEY'] = DUMMY_API_KEY
    with open("wandb-history.jsonl", "w") as f:
        f.write('{"acc":25}')
    result = runner.invoke(cli.sync, ["--id", "7ojulnsc", "."])
    print(result.output)
    print(result.exception)
    print(traceback.print_tb(result.exc_info[2]))
    assert "Uploading history metrics" in str(result.output)
    assert result.exit_code == 0

@pytest.mark.skipif(os.getenv("NO_ML") == "true" or sys.version_info < (3, 5), reason="Tensorboard not installed and we don't support tensorboard syncing in py2")
def test_sync_tensorboard_ignore(runner, git_repo, mock_server):
    # Un comment this line when re-recording the cassette
    os.environ['WANDB_API_KEY'] = DUMMY_API_KEY
    wandb.util.mkdir_exists_ok("logs/train")
    wandb.util.mkdir_exists_ok("logs/val")
    with open("logs/garbage.txt", "w") as f:
        f.write("NOTHING")
    tf_events="events.out.tfevents.111.test.localdomain"
    shutil.copyfile(os.path.dirname(__file__) + "/fixtures/"+tf_events, "./logs/train/"+tf_events)
    shutil.copyfile(os.path.dirname(__file__) + "/fixtures/"+tf_events, "./logs/val/"+tf_events)
    result = runner.invoke(cli.sync, ["--id", "abc123", "-e", "vanpelt", "--ignore", "garbage.txt", "logs"], env=os.environ)
    print(result.output)
    print(result.exception)
    print(traceback.print_tb(result.exc_info[2]))
    assert "Found tfevents file, converting..." in str(result.output)
    assert result.exit_code == 0

@pytest.mark.skipif(os.getenv("NO_ML") == "true" or sys.version_info < (3, 5), reason="Tensorboard not installed and we don't support tensorboard syncing in py2")
def test_sync_tensorboard_single(runner, git_repo, mock_server):
    # Un comment this line when re-recording the cassette
    os.environ['WANDB_API_KEY'] = DUMMY_API_KEY
    wandb.util.mkdir_exists_ok("logs")
    tf_events="events.out.tfevents.111.simple.localdomain"
    shutil.copyfile(os.path.dirname(__file__) + "/fixtures/"+tf_events, "./logs/"+tf_events)
    result = runner.invoke(cli.sync, ["--id", "abc123", "-e", "vanpelt", "logs"], env=os.environ)
    print(result.output)
    print(result.exception)
    print(traceback.print_tb(result.exc_info[2]))
    assert "Found tfevents file, converting..." in str(result.output)
    assert "WARNING Not logging key \"histo\"" in str(result.output)
    assert result.exit_code == 0
    print(mock_server.requests["file_stream"][0]["files"]["wandb-history.jsonl"]["content"])
    assert len(json.loads(mock_server.requests["file_stream"][0]["files"]["wandb-history.jsonl"]["content"][0]).keys()) == 5


def test_sync_runs(runner, request_mocker, upsert_run, upload_url, upload_logs, query_viewer, git_repo):
    os.environ["WANDB_API_KEY"] = "some invalid key"
    query_viewer(request_mocker)
    upsert_run(request_mocker)
    upload_url(request_mocker)
    upload_logs(request_mocker, "abc123zz")
    upload_logs(request_mocker, "cba321zz")
    run_1 = "wandb/run-120199-abc123zz"
    run_2 = "wandb/dryrun-120300-cba321zz"
    wandb.util.mkdir_exists_ok(run_1)
    wandb.util.mkdir_exists_ok(run_2)
    with open(run_1 + "/wandb-history.jsonl", "w") as f:
        f.write('{"acc":25}')
    with open(run_2 + "/wandb-history.jsonl", "w") as f:
        f.write('{"acc":25}')
    result = runner.invoke(cli.sync, ".")
    print(result.output)
    print(result.exception)
    print(traceback.print_tb(result.exc_info[2]))
    found = re.findall(r"Uploading history metrics", str(result.output))
    assert len(found) == 2


def test_run_simple(runner, git_repo, mock_server, monkeypatch):
    run_id = "abc123"
    with open("simple.py", "w") as f:
        f.write('print("Done!")')
    print(os.getcwd())
    monkeypatch.setattr('time.sleep', lambda s: True)
    result = runner.invoke(
        cli.run, ["--id=%s" % run_id, "python", "simple.py"])
    print(result.output)
    print(result.exception)
    print(traceback.print_tb(result.exc_info[2]))
    # This is disabled for now because it hasn't worked for a long time:
    #assert "Verifying uploaded files... verified!" in result.output
    assert result.exit_code == 0
    assert "Syncing run lovely-dawn-32" in result.output

def test_run_ignore_diff(runner, git_repo, mock_server, monkeypatch):
    run_id = "abc123"
    os.environ["WANDB_IGNORE_GLOBS"] = "*.patch"
    with open("simple.py", "w") as f:
        f.write('print("Done!")')
    with open("README", "w") as f:
        f.write("Making it dirty")
    print(os.getcwd())
    result = runner.invoke(
        cli.run, ["--id=%s" % run_id, "python", "simple.py"])
    print(result.output)
    print(result.exception)
    print(traceback.print_tb(result.exc_info[2]))
    # This is disabled for now because it hasn't worked for a long time:
    #assert "Verifying uploaded files... verified!" in result.output
    assert result.exit_code == 0
    assert "Syncing run lovely-dawn-32" in result.output
    assert 'storage?file=diff.patch' not in mock_server.requests.keys()
    wandb.reset_env()

@pytest.mark.skipif(os.getenv("NO_ML") == "true" or platform.system() == "@indows", reason="No PIL in NO_ML, this was failing in windows for some reason")
def test_run_image(runner, git_repo, mock_server):
    run_id = "123abc"
    with open("image.py", "w") as f:
        f.write("""import wandb
import sys
import numpy as np

wandb.init(entity="test", project="test")
wandb.log({"img": [wandb.Image(np.ones((28,28,1)))]})
""")
    result = runner.invoke(cli.run, ["--id=%s" % run_id, "python", "image.py"])
    print(result.output)
    print(result.exception)
    #print(traceback.print_tb(result.exc_info[2]))
    assert result.exit_code == 0
    assert "Syncing run lovely-dawn-32" in result.output
    assert "CommError" not in result.output


@pytest.mark.skip("Sweep command is disabled")
def test_sweep_no_config(runner):
    result = runner.invoke(cli.sweep, ["missing.yaml"])
    print(result.output)
    print(result.exception)
    print(traceback.print_tb(result.exc_info[2]))
    assert "ERROR: Couldn't open sweep file" in result.output
    assert result.exit_code == 0


@pytest.mark.skip("Bring the board back")
def test_board_error(runner, git_repo):
    result = runner.invoke(cli.board)
    print(result.output)
    print(result.exception)
    print(traceback.print_tb(result.exc_info[2]))
    assert result.exit_code == 1
    assert "No runs found in this directory" in result.output


@pytest.mark.skip("Bring the board back")
def test_board_bad_dir(runner, mocker):
    result = runner.invoke(cli.board, ["--logdir", "non-existent"])
    print("F", result.output)
    print("E", result.exception)
    print(traceback.print_tb(result.exc_info[2]))
    assert result.exit_code != 0
    assert "Directory does not exist" in str(result.output)


@pytest.mark.skip("Bring the board back")
def test_board_custom_dir(runner, mocker, monkeypatch):
    from wandb.board.tests.util import basic_fixture_path
    from wandb.board.app.graphql.loader import load
    app = mocker.MagicMock()

    def create(config, path):
        load(path)
        return app
    monkeypatch.setattr('wandb.board.create_app', create)
    result = runner.invoke(cli.board, ["--logdir", basic_fixture_path])
    print(result.output)
    print(result.exception)
    print(traceback.print_tb(result.exc_info[2]))
    assert result.exit_code == 0
    assert app.run.called


def test_resume_never(runner, request_mocker, upsert_run, query_run_resume_status, git_repo, query_viewer):
    query_viewer(request_mocker)
    query_run_resume_status(request_mocker)
    upsert_run(request_mocker, error=['Bucket with that name already exists'])
    # default is --resume="never"
    result = runner.invoke(cli.run, ["missing.py"])
    print(result.output)
    print(result.exception)
    print(traceback.print_tb(result.exc_info[2]))
    assert "resume='never'" in str(result.output)
    assert result.exit_code == 1


def test_resume_must(runner, request_mocker, query_no_run_resume_status, query_viewer, git_repo):
    query_no_run_resume_status(request_mocker)
    query_viewer(request_mocker)
    result = runner.invoke(cli.run, ["--resume=must", "missing.py"])
    print(result.output)
    print(result.exception)
    print(traceback.print_tb(result.exc_info[2]))
    assert "resume='must'" in str(result.output)
    assert result.exit_code == 1

# TODO: test actual resume
