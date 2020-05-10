import pytest
from wandb.apis import artifacts
from .utils import runner

def test_one_file_manifest(runner):
    with runner.isolated_filesystem():
        open('file1.txt', 'w').write('hello')
        artifact = artifacts.Artifact(type='dataset')
        artifact.add_file('file1.txt')

        # This checks the L0 (server) manifest digest.
        assert artifact.digest == '0365175c40e8b18c029bd49bf7d0cf99'