import wandb
import random
import os
import time

PROJECT_NAME = 'serialize-artifact-test'
FILE_NAME = 'contents.txt'
NUM_VERSIONS = 50

artifact_name = 'serialized-%s' % time.time()

# write random artifacts serially
with wandb.init(project=PROJECT_NAME) as run:
    for i in range(NUM_VERSIONS):
        art = wandb.Artifact(artifact_name, type='dataset')
        open(FILE_NAME, 'w').write('%s %s' % (i, 'x' * random.randrange(50000)))
        art.add_file(FILE_NAME)
        run.log_artifact(art)

# confirm that the versions end up in the order we sent them!
api = wandb.Api()
versions = api.artifact_versions('dataset', '%s/%s' % (PROJECT_NAME, artifact_name))
print("VERSIONS", versions)
for av in versions:
    version = av.name.split(':')[1]  # e.g. v14
    version = version[1:]  # strip leading v
    ver_dir = av.download()
    file_contents = open(os.path.join(ver_dir, FILE_NAME)).read()
    file_version = file_contents.split()[0]
    print('%s == %s' % (version, file_version))
    assert version == file_version
