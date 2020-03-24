import pytest
from wandb.apis import artifacts
from .utils import runner

def test_empty_manifest():
    with pytest.raises(ValueError):
        artifacts.LocalArtifactManifestV1([])

def test_one_file_manifest(runner):
    with runner.isolated_filesystem():
        open('file1.txt', 'w').write('hello')
        dig = artifacts.LocalArtifactManifestV1(['file1.txt']).digest
        assert dig == '8999ba3788b3e39321b6556d4437bb8c'