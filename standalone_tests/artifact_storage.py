import random
import os
import sys
import tempfile

import wandb

def artifact_with_various_paths():
    art = wandb.Artifact(type='artsy', name='my artys')

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
    with wandb.init(reinit=True, job_type='user') as run:
        # Use artifact that doesn't exist
        art2 = artifact_with_various_paths()
        run.use_artifact(art2)

    with wandb.init(reinit=True, job_type='writer') as run:
        # Log artifact that doesn't exist
        art1 = artifact_with_various_paths()
        run.log_artifact(art1)

    with wandb.init(reinit=True, job_type='reader') as run:
        # Downloading should probably fail or warn when your artifact contains
        # a path that can't be downloaded.
        print('Downloading art1')
        art = run.use_artifact(type='artsy', name=art1.digest)

        import pprint
        pprint.pprint(art._load_manifest().to_manifest_json())
        # print(art.list())
        art_dir = art.download()
        print(os.listdir(art_dir))
        print('Art bla.txt reference', art.get_path('bla.txt').ref())
        print('Art requirements.txt reference', art.get_path('requirements.txt').ref())
        print('Art requirements.txt reference', art.get_path('requirements.txt').download())

        print('Downloading art2')
        art = run.use_artifact(type='artsy', name=art2.digest)
        art_dir = art.download()
        print(os.listdir(art_dir))

    

if __name__ == '__main__':
    main(sys.argv)