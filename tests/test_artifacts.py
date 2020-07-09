import os
import pytest
import wandb
from wandb import artifacts
from wandb import util
from .utils import runner

def mock_boto(artifact, path=False):
    class S3Object(object):
        def __init__(self, name='my_object.pb', metadata=None):
            self.metadata = metadata or {"md5": "1234567890abcde"}
            self.e_tag = '"1234567890abcde"'
            self.version_id = "1"
            self.name = name
            self.key = name
            self.content_length = 10

        def load(self):
            if path:
                raise util.get_module("botocore").exceptions.ClientError({"Error": {"Code": "404"}}, "HeadObject")

    class Filtered(object):
        def limit(self, *args, **kwargs):
            return [S3Object(), S3Object(name="my_other_object.pb")]

    class S3Objects(object):
        def filter(self, **kwargs):
            return Filtered()

    class S3Bucket(object):
        def __init__(self, *args, **kwargs):
            self.objects = S3Objects()

    class S3Resource(object):
        def Object(self, bucket, key):
            return S3Object()

        def Bucket(self, bucket):
            return S3Bucket()

    mock = S3Resource()
    handler = artifact._storage_policy._handler._handlers["s3"]
    handler._s3 = mock
    handler._botocore = util.get_module("botocore")
    return mock

def mock_gcs(artifact, path=False):
    class Blob(object):
        def __init__(self, name='my_object.pb', metadata=None):
            self.md5_hash = "1234567890abcde"
            self.etag = '1234567890abcde'
            self.generation = "1"
            self.name = name
            self.size = 10

    class GSBucket(object):
        def get_blob(self,*args, **kwargs):
            return None if path else Blob()

        def list_blobs(self, *args, **kwargs):
            return [Blob(), Blob(name="my_other_object.pb")]

    class GSClient(object):
        def bucket(self, bucket):
            return GSBucket()

    mock = GSClient()
    handler = artifact._storage_policy._handler._handlers["gs"]
    handler._client = mock
    return mock

def test_add_one_file(runner):
    with runner.isolated_filesystem():
        with open('file1.txt', 'w') as f:
            f.write('hello')
        artifact = artifacts.Artifact(type='dataset', name='my-arty')
        artifact.add_file('file1.txt')

        assert artifact.digest == 'a00c2239f036fb656c1dcbf9a32d89b4'
        manifest = artifact.manifest.to_manifest_json()
        assert manifest['contents']['file1.txt'] == {
            'digest': 'XUFAKrxLKna5cZ2REBfFkg==', 'size': 5}

def test_add_named_file(runner):
    with runner.isolated_filesystem():
        with open('file1.txt', 'w') as f:
            f.write('hello')
        artifact = artifacts.Artifact(type='dataset', name='my-arty')
        artifact.add_file('file1.txt', name='great-file.txt')

        assert artifact.digest == '585b9ada17797e37c9cbab391e69b8c5'
        manifest = artifact.manifest.to_manifest_json()
        assert manifest['contents']['great-file.txt'] == {
            'digest': 'XUFAKrxLKna5cZ2REBfFkg==', 'size': 5}

def test_add_new_file(runner):
    with runner.isolated_filesystem():
        artifact = artifacts.Artifact(type='dataset', name='my-arty')
        with artifact.new_file('file1.txt') as f:
            f.write('hello')

        assert artifact.digest == 'a00c2239f036fb656c1dcbf9a32d89b4'
        manifest = artifact.manifest.to_manifest_json()
        assert manifest['contents']['file1.txt'] == {
            'digest': 'XUFAKrxLKna5cZ2REBfFkg==', 'size': 5}

def test_add_dir(runner):
    with runner.isolated_filesystem():
        open('file1.txt', 'w').write('hello')
        artifact = artifacts.Artifact(type='dataset', name='my-arty')
        artifact.add_dir('.')

        assert artifact.digest == 'a00c2239f036fb656c1dcbf9a32d89b4'
        manifest = artifact.manifest.to_manifest_json()
        assert manifest['contents']['file1.txt'] == {
            'digest': 'XUFAKrxLKna5cZ2REBfFkg==', 'size': 5}

def test_add_named_dir(runner):
    with runner.isolated_filesystem():
        open('file1.txt', 'w').write('hello')
        artifact = artifacts.Artifact(type='dataset', name='my-arty')
        artifact.add_dir('.', name='subdir')

        assert artifact.digest == 'a757208d042e8627b2970d72a71bed5b'

        manifest = artifact.manifest.to_manifest_json()
        assert manifest['contents']['subdir/file1.txt'] == {
            'digest': 'XUFAKrxLKna5cZ2REBfFkg==', 'size': 5}

def test_add_reference_local_file(runner):
    with runner.isolated_filesystem():
        open('file1.txt', 'w').write('hello')
        artifact = artifacts.Artifact(type='dataset', name='my-arty')
        artifact.add_reference('file://file1.txt')

        assert artifact.digest == 'a00c2239f036fb656c1dcbf9a32d89b4'
        manifest = artifact.manifest.to_manifest_json()
        assert manifest['contents']['file1.txt'] == {
            'digest': 'XUFAKrxLKna5cZ2REBfFkg==', 'ref': 'file://file1.txt', 'size': 5}

def test_add_reference_local_file_no_checksum(runner):
    with runner.isolated_filesystem():
        open('file1.txt', 'w').write('hello')
        artifact = artifacts.Artifact(type='dataset', name='my-arty')
        artifact.add_reference('file://file1.txt', checksum=False)

        assert artifact.digest == '2f66dd01e5aea4af52445f7602fe88a0'
        manifest = artifact.manifest.to_manifest_json()
        assert manifest['contents']['file1.txt'] == {
            'digest': 'file://file1.txt', 'ref': 'file://file1.txt'}

def test_add_reference_local_dir(runner):
    with runner.isolated_filesystem():
        open('file1.txt', 'w').write('hello')
        open('file2.txt', 'w').write('dude')
        artifact = artifacts.Artifact(type='dataset', name='my-arty')
        artifact.add_reference('file://'+os.getcwd())

        assert artifact.digest == '5e8e98ebd59cc93b58d0cb26432d4720'
        manifest = artifact.manifest.to_manifest_json()
        assert manifest['contents']['file1.txt'] == {
            'digest': 'XUFAKrxLKna5cZ2REBfFkg==', 'ref': 'file://'+os.getcwd()+'/file1.txt', 'size': 5}
        assert manifest['contents']['file2.txt'] == {
            'digest': 'E7c+2uhEOZC+GqjxpIO8Jw==', 'ref': 'file://'+os.getcwd()+'/file2.txt', 'size': 4}

def test_add_s3_reference_object(runner, mocker):
    with runner.isolated_filesystem():
        artifact = artifacts.Artifact(type="dataset", name='my-arty')
        mock_boto(artifact)
        artifact.add_reference("s3://my-bucket/my_object.pb")

        assert artifact.digest == '8aec0d6978da8c2b0bf5662b3fd043a4'
        manifest = artifact.manifest.to_manifest_json()
        assert manifest['contents']['my_object.pb'] == {
            'digest': '1234567890abcde', 'ref': 's3://my-bucket/my_object.pb',
            'extra': {'etag': '1234567890abcde', 'versionID': '1'}, 'size': 10}

def test_add_s3_reference_path(runner, mocker, capsys):
    with runner.isolated_filesystem():
        artifact = artifacts.Artifact(type="dataset", name='my-arty')
        mock_boto(artifact, path=True)
        artifact.add_reference("s3://my-bucket/")

        assert artifact.digest == '17955d00a20e1074c3bc96c74b724bfe'
        manifest = artifact.manifest.to_manifest_json()
        assert manifest['contents']['my_object.pb'] == {
            'digest': '1234567890abcde', 'ref': 's3://my-bucket/my_object.pb',
            'extra': {'etag': '1234567890abcde', 'versionID': '1'}, 'size': 10}
        _, err = capsys.readouterr()
        assert "Generating checksum" in err

def test_add_s3_max_objects(runner, mocker, capsys):
    with runner.isolated_filesystem():
        artifact = artifacts.Artifact(type="dataset", name='my-arty')
        mock_boto(artifact, path=True)
        with pytest.raises(ValueError):
            artifact.add_reference("s3://my-bucket/", max_objects=1)

def test_add_reference_s3_no_checksum(runner):
    with runner.isolated_filesystem():
        open('file1.txt', 'w').write('hello')
        artifact = artifacts.Artifact(type='dataset', name='my-arty')
        # TODO: Should we require name in this case?
        artifact.add_reference('s3://my_bucket/file1.txt', checksum=False)

        assert artifact.digest == '52631787ed3579325f985dc0f2374040'
        manifest = artifact.manifest.to_manifest_json()
        assert manifest['contents']['file1.txt'] == {
            'digest': 's3://my_bucket/file1.txt', 'ref': 's3://my_bucket/file1.txt'}

def test_add_gs_reference_object(runner, mocker):
    with runner.isolated_filesystem():
        artifact = artifacts.Artifact(type="dataset", name='my-arty')
        mock_gcs(artifact)
        artifact.add_reference("gs://my-bucket/my_object.pb")

        assert artifact.digest == '8aec0d6978da8c2b0bf5662b3fd043a4'
        manifest = artifact.manifest.to_manifest_json()
        assert manifest['contents']['my_object.pb'] == {
            'digest': '1234567890abcde', 'ref': 'gs://my-bucket/my_object.pb',
            'extra': {'etag': '1234567890abcde', 'versionID': '1'}, 'size': 10}

def test_add_gs_reference_path(runner, mocker, capsys):
    with runner.isolated_filesystem():
        artifact = artifacts.Artifact(type="dataset", name='my-arty')
        mock_gcs(artifact, path=True)
        artifact.add_reference("gs://my-bucket/")

        assert artifact.digest == '17955d00a20e1074c3bc96c74b724bfe'
        manifest = artifact.manifest.to_manifest_json()
        assert manifest['contents']['my_object.pb'] == {
            'digest': '1234567890abcde', 'ref': 'gs://my-bucket/my_object.pb',
            'extra': {'etag': '1234567890abcde', 'versionID': '1'}, 'size': 10}
        _, err = capsys.readouterr()
        assert "Generating checksum" in err

def test_add_reference_named_local_file(runner):
    with runner.isolated_filesystem():
        open('file1.txt', 'w').write('hello')
        artifact = artifacts.Artifact(type='dataset', name='my-arty')
        artifact.add_reference('file://file1.txt', name='great-file.txt')

        assert artifact.digest == '585b9ada17797e37c9cbab391e69b8c5'
        manifest = artifact.manifest.to_manifest_json()
        assert manifest['contents']['great-file.txt'] == {
            'digest': 'XUFAKrxLKna5cZ2REBfFkg==', 'ref': 'file://file1.txt', 'size': 5}

def test_add_reference_unknown_handler(runner):
    with runner.isolated_filesystem():
        artifact = artifacts.Artifact(type='dataset', name='my-arty')
        artifact.add_reference('http://example.com/somefile.txt', name='ref')

        assert artifact.digest == '5b8876252f3ca922c164de380089c9ae'

        manifest = artifact.manifest.to_manifest_json()
        assert manifest['contents']['ref'] == {
            'digest': 'http://example.com/somefile.txt', 'ref': 'http://example.com/somefile.txt'}

def test_log_artifact_simple(runner, wandb_init_run):
    util.mkdir_exists_ok("artsy")
    open("artsy/file1.txt", "w").write("hello")
    open("artsy/file2.txt", "w").write("goodbye")
    with pytest.raises(ValueError):
        wandb.log_artifact("artsy")
    art = wandb.log_artifact("artsy", type="dataset")
    assert art.name == "run-"+wandb_init_run.id+"-artsy"

def test_use_artifact_simple(runner, wandb_init_run):
    art = wandb.use_artifact("mnist:v0", type="dataset")
    assert art.name == "mnist:v0"
    path = art.download()
    assert os.path.exists(path)