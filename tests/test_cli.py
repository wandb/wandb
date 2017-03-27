import pytest, os, traceback
from wandb import cli, Api
from click.testing import CliRunner
from .api_mocks import *

@pytest.fixture
def runner():
    return CliRunner()

@pytest.fixture
def empty_netrc(mocker):
    netrc = mocker.patch("netrc.netrc")
    mock = mocker.MagicMock()
    mock.hosts.__getitem__.side_effect = lambda k: None
    netrc.return_value = mock

@pytest.fixture
def local_netrc(mocker):
    #TODO: this seems overkill / BROKEN
    origexpand = os.path.expanduser
    def expand(path):
        print(path, "netrc" in path)
        return os.path.realpath("netrc") if "netrc" in path else origexpand(path)
    return mocker.patch("os.path.expanduser", side_effect=expand)

def test_help(runner):
    result = runner.invoke(cli.cli)
    assert result.exit_code == 0
    assert 'Console script for wandb' in result.output
    help_result = runner.invoke(cli.cli, ['--help'])
    assert help_result.exit_code == 0
    assert '--help  Show this message and exit.' in help_result.output

def test_config(runner):
    with runner.isolated_filesystem():
        with open('.wandb', 'w') as f:
            f.write("""[default]
model: cli_test
entity: cli_test
            """)
        result = runner.invoke(cli.models, default_map=Api().config())
        assert "cli_test" in result.output

def test_upload(runner, request_mocker, query_model, upload_url):
    query_model(request_mocker)
    upload_url(request_mocker)
    with runner.isolated_filesystem():
        with open('fake.h5', 'wb') as f:
            f.write(os.urandom(10000000))
        result = runner.invoke(cli.upload, ['fake.h5'], input="test\n")
        assert result.exit_code == 0
        assert "Uploading model: test" in result.output

def test_download(runner, request_mocker, query_model, download_url):
    query_model(request_mocker)
    download_url(request_mocker)
    with runner.isolated_filesystem():
        result = runner.invoke(cli.download, ['--model', 'test'])
        assert result.exit_code == 0
        assert "Downloading model: test" in result.output
        assert os.path.isfile("weights.url")

def test_bump(runner, request_mocker, mutate_revision):
    mutate_revision(request_mocker)
    result = runner.invoke(cli.bump, ['--model', 'test'])
    #In case there is a cryptic error
    #print(traceback.print_tb(result.exc_info[2]))
    assert result.exit_code == 0
    assert "Bumped version to: 0.0.1" in result.output
    
def test_models(runner, request_mocker, query_models):
    query_models(request_mocker)
    result = runner.invoke(cli.models)
    assert result.exit_code == 0
    assert "test_2 - Test model" in result.output

def test_models_error(runner, request_mocker, query_models):
    query_models(request_mocker, status_code=400)
    result = runner.invoke(cli.models)
    assert result.exit_code == 0
    print(result.output)
    assert "ERROR" in result.output

def test_init_new_login(runner, empty_netrc, local_netrc, request_mocker, query_models):
    query_models(request_mocker)
    with runner.isolated_filesystem():
        result = runner.invoke(cli.init, input="vanpelt\n12345\ntest_model")
        assert result.exit_code == 0
        with open("netrc", "r") as f:
            generatedNetrc = f.read()
        with open(".wandb", "r") as f:
            generatedWandb = f.read()
        assert "12345" in generatedNetrc
        assert "test_model" in generatedWandb

def test_init_add_login(runner, empty_netrc, local_netrc, request_mocker, query_models):
    query_models(request_mocker)
    with runner.isolated_filesystem():
        with open("netrc", "w") as f:
            f.write("previous config")
        result = runner.invoke(cli.init, input="vanpelt\n12345\ntest_model")
        assert result.exit_code == 0
        with open("netrc", "r") as f:
            generatedNetrc = f.read()
        with open(".wandb", "r") as f:
            generatedWandb = f.read()
        assert "12345" in generatedNetrc
        assert "previous config" in generatedNetrc

@pytest.mark.skip(reason="Can't figure out how to mock expanduser / deal with no $HOME")
def test_existing_login(runner, local_netrc, request_mocker, query_models):
    query_models(request_mocker)
    with runner.isolated_filesystem():
        with open("netrc", "w") as f:
            f.write("api.wandb.ai\n\ttest\t12345")
        result = runner.invoke(cli.init, input="vanpelt\ntest_model")
        print(result.exception)
        print(traceback.print_tb(result.exc_info[2]))
        assert result.exit_code == 0
        with open(".wandb", "r") as f:
            generatedWandb = f.read()
        assert "test_model" in generatedWandb
        assert "This directory is configured" in result.output
