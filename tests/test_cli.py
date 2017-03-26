import pytest, os, traceback
from wandb import cli, Api
from click.testing import CliRunner
from .mocks import *

@pytest.fixture
def runner():
    return CliRunner()

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
