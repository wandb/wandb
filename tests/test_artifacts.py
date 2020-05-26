import os
import pytest
from wandb import artifacts
from .utils import runner

def test_add_one_file(runner):
    with runner.isolated_filesystem():
        with open('file1.txt', 'w') as f:
            f.write('hello')
        artifact = artifacts.Artifact(type='dataset')
        artifact.add_file('file1.txt')

        assert artifact.digest == 'a00c2239f036fb656c1dcbf9a32d89b4'
        manifest = artifact.manifest.to_manifest_json()
        assert manifest['contents']['file1.txt'] == {
            'digest': 'XUFAKrxLKna5cZ2REBfFkg==', 'size': 5}

def test_add_named_file(runner):
    with runner.isolated_filesystem():
        with open('file1.txt', 'w') as f:
            f.write('hello')
        artifact = artifacts.Artifact(type='dataset')
        artifact.add_file('file1.txt', name='great-file.txt')

        assert artifact.digest == '585b9ada17797e37c9cbab391e69b8c5'
        manifest = artifact.manifest.to_manifest_json()
        assert manifest['contents']['great-file.txt'] == {
            'digest': 'XUFAKrxLKna5cZ2REBfFkg==', 'size': 5}

def test_add_new_file(runner):
    with runner.isolated_filesystem():
        artifact = artifacts.Artifact(type='dataset')
        with artifact.new_file('file1.txt') as f:
            f.write('hello')

        assert artifact.digest == 'a00c2239f036fb656c1dcbf9a32d89b4'
        manifest = artifact.manifest.to_manifest_json()
        assert manifest['contents']['file1.txt'] == {
            'digest': 'XUFAKrxLKna5cZ2REBfFkg==', 'size': 5}

def test_add_dir(runner):
    with runner.isolated_filesystem():
        open('file1.txt', 'w').write('hello')
        artifact = artifacts.Artifact(type='dataset')
        artifact.add_dir('.')

        assert artifact.digest == 'a00c2239f036fb656c1dcbf9a32d89b4'
        manifest = artifact.manifest.to_manifest_json()
        assert manifest['contents']['file1.txt'] == {
            'digest': 'XUFAKrxLKna5cZ2REBfFkg==', 'size': 5}

def test_add_named_dir(runner):
    with runner.isolated_filesystem():
        open('file1.txt', 'w').write('hello')
        artifact = artifacts.Artifact(type='dataset')
        artifact.add_dir('.', name='subdir')

        assert artifact.digest == 'a757208d042e8627b2970d72a71bed5b'

        manifest = artifact.manifest.to_manifest_json()
        assert manifest['contents']['subdir/file1.txt'] == {
            'digest': 'XUFAKrxLKna5cZ2REBfFkg==', 'size': 5}

def test_add_reference_local_file(runner):
    with runner.isolated_filesystem():
        open('file1.txt', 'w').write('hello')
        artifact = artifacts.Artifact(type='dataset')
        artifact.add_reference('file://file1.txt')

        assert artifact.digest == 'a00c2239f036fb656c1dcbf9a32d89b4'
        manifest = artifact.manifest.to_manifest_json()
        assert manifest['contents']['file1.txt'] == {
            'digest': 'XUFAKrxLKna5cZ2REBfFkg==', 'ref': 'file://file1.txt', 'size': 5}

def test_add_reference_named_local_file(runner):
    with runner.isolated_filesystem():
        open('file1.txt', 'w').write('hello')
        artifact = artifacts.Artifact(type='dataset')
        artifact.add_reference('file://file1.txt', name='great-file.txt')

        assert artifact.digest == '585b9ada17797e37c9cbab391e69b8c5'
        manifest = artifact.manifest.to_manifest_json()
        assert manifest['contents']['great-file.txt'] == {
            'digest': 'XUFAKrxLKna5cZ2REBfFkg==', 'ref': 'file://file1.txt', 'size': 5}

def test_add_reference_unknown_handler(runner):
    with runner.isolated_filesystem():
        artifact = artifacts.Artifact(type='dataset')
        artifact.add_reference('http://example.com/somefile.txt', name='ref')

        assert artifact.digest == '5b8876252f3ca922c164de380089c9ae'

        manifest = artifact.manifest.to_manifest_json()
        assert manifest['contents']['ref'] == {
            'digest': 'http://example.com/somefile.txt', 'ref': 'http://example.com/somefile.txt'}