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
        assert dig == 'a43ea3ce45f60ca3b2b7e7a7ce184a23'