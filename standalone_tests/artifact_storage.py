import random
import os
import sys
import tempfile

import wandb
from wandb.compat import tempfile

def artifact_with_various_paths():
    art = wandb.Artifact(type='artsy', name='my-artys')

    # internal file
    with open('random.txt', 'w') as f:
        f.write('file1 %s' % random.random())
        f.close()
        art.add_file(f.name)
    # internal file (using new_file)
    with art.new_file('a.txt') as f:
        f.write('hello %s' % random.random())
    os.makedirs('./dir', exist_ok=True)
    with open('./dir/1.txt', 'w') as f:
        f.write('1')
    with open('./dir/2.txt', 'w') as f:
        f.write('2')
    art.add_dir('./dir')

    with open('bla.txt', 'w') as f:
        f.write('BLAAAAAAAAAAH')

    # reference to local file
    art.add_reference('file://bla.txt')
    # # reference to s3 file
    art.add_reference('s3://wandb-test-file-storage/annirudh/loadtest/19r6ajhm/requirements.txt')
    # # reference to s3 prefix
    # art.add_reference('s3://wandb-test-file-storage/annirudh/loadtest/19r6ajhm')
    # # http reference
    # art.add_reference('https://i.imgur.com/0ZfJ9xj.png')
    # # reference to unknown scheme
    # art.add_reference('detectron2://some-model', name='x')

    return art 


def main(argv):
    # set global entity and project before chdir'ing
    from wandb.apis import InternalApi
    api = InternalApi()
    os.environ['WANDB_ENTITY'] = api.settings('entity')
    os.environ['WANDB_PROJECT'] = api.settings('project')

    # Change dir to avoid litering code directory
    tempdir = tempfile.TemporaryDirectory()
    os.chdir(tempdir.name)

    with wandb.init(reinit=True, job_type='user') as run:
        # Use artifact that doesn't exist
        art2 = artifact_with_various_paths()
        run.use_artifact(art2, aliases='art2')

    with wandb.init(reinit=True, job_type='writer') as run:
        # Log artifact that doesn't exist
        art1 = artifact_with_various_paths()
        run.log_artifact(art1, aliases='art1')

    with wandb.init(reinit=True, job_type='reader') as run:
        # Downloading should probably fail or warn when your artifact contains
        # a path that can't be downloaded.
        print('Downloading art1')
        art = run.use_artifact('my-artys:art1')

        import pprint
        pprint.pprint(art._load_manifest().to_manifest_json())
        # print(art.list())
        art_dir = art.download()
        print(os.listdir(art_dir))
        print('Art bla.txt reference', art.get_path('bla.txt').ref_target())
        print('Art requirements.txt reference', art.get_path('requirements.txt').ref_target())
        print('Art requirements.txt reference', art.get_path('requirements.txt').download())

        print('Downloading art2')
        art = run.use_artifact('my-artys:art2')
        art_dir = art.download()
        art.verify()
        print(os.listdir(art_dir))

        computed = wandb.Artifact('bla', type='dataset')
        computed.add_dir(art_dir)

        # These won't match, because we stored an s3 reference which uses the
        # etag, so the manifest's sadly aren't directly comparable
        print('Not expected to match because of s3 ref:')
        print('downloaded dig', art.digest)
        print('computed dig', computed.digest)

        import json
        print('downloaded manifest', art._load_manifest().to_manifest_json())
        print('computed manifest', computed.manifest.to_manifest_json())

    

if __name__ == '__main__':
    main(sys.argv)