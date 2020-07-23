"""artifact load test.

For a single artifact named A:            
- test phase (run max T seconds)
  - generate 100k random files of size S      
  - have W parallel writer processes that create new versions for A from a random subset of those files
  - have R parallel reader processes randomly pick a version from A, download it, and verify it (through cache)
  - have a cache gc process that runs cache gc periodically      
  - have a deleter process that wakes up periodically and deletes random versions using the API.      
  - have a bucket gc process that runs bucket gc periodically      
- verification phase:
  - artifact verification
    - ensure all versions are in the committed or deleted states
  - bucket verification
    - run bucket gc one more time
    - ensure bucket state exactly matches state of all manifests
      - ensure files are available in bucket and match md5 / etag                             
      - ensure there are no dangling files in bucket 

TODO:
  - enabling the cache gc process causes errors, but the test doesn't fail, because
    wandb exits cleanly even if file pusher has errors
  - implement the deleter and bucket gc processes once we've built support for them
  - implement the bucket verification process
"""

import argparse
import random
import multiprocessing
import os
import queue
import string
import sys
import time
from tqdm import tqdm

import wandb
from wandb.compat import tempfile

parser = argparse.ArgumentParser(description='artifacts load test')

# gen file args
parser.add_argument('--gen_n_files', type=int, required=True,
                    help='Path to dataset directory')
parser.add_argument('--gen_max_small_size', type=int, required=True)
parser.add_argument('--gen_max_large_size', type=int, required=True)

parser.add_argument('--test_phase_seconds', type=int, required=True)

# writer args
parser.add_argument('--num_writers', type=int, required=True)
parser.add_argument('--files_per_version_min', type=int, required=True)
parser.add_argument('--files_per_version_max', type=int, required=True)

# reader args
parser.add_argument('--num_readers', type=int, required=True)

# cache garbage collector args
parser.add_argument('--cache_gc_period_max', type=int)


def gen_files(n_files, max_small_size, max_large_size):
    bufsize = max_large_size * 100

    # create a random buffer to pull from. drawing ranges from this buffer is
    # orders of magnitude faster than creating random contents for each file.
    buf = ''.join(random.choices(string.ascii_uppercase + string.digits, k=bufsize))

    fnames = []
    for i in tqdm(range(n_files)):
        full_dir = os.path.join('source_files', '%s' % (i % 4))
        os.makedirs(full_dir, exist_ok=True)
        fname = os.path.join(full_dir, '%s.txt' % i)
        fnames.append(fname)
        with open(fname, 'w') as f:
            small = random.random() < 0.5
            if small:
                size = int(random.random() * max_small_size)
            else:
                size = int(random.random() * max_large_size)
            start_pos = int(random.random() * (bufsize - size))
            f.write(buf[start_pos:start_pos+size])

    return fnames

def proc_version_writer(stop_queue, fnames, artifact_name, files_per_version_min, files_per_version_max):
    while True:
        try:
            stop_queue.get_nowait()
            print('Writer stopping')
            return
        except queue.Empty:
            pass
        print('Writer initing run')
        with wandb.init(reinit=True, job_type='writer') as run:
            files_in_version = random.randrange(files_per_version_min, files_per_version_max)
            version_fnames = random.sample(fnames, files_in_version)
            art = wandb.Artifact(artifact_name, type='dataset')
            for version_fname in version_fnames:
                art.add_file(version_fname)
            run.log_artifact(art)

def proc_version_reader(stop_queue, artifact_name, reader_id):
    api = wandb.Api()
    # initial sleep to ensure we've created the sequence. Public API fails
    # with a nasty error if not.
    time.sleep(10)
    while True:
        try:
            stop_queue.get_nowait()
            print('Reader stopping')
            return
        except queue.Empty:
            pass
        versions = api.artifact_versions('dataset', artifact_name)
        versions = [v for v in versions if v.state == 'COMMITTED']
        if len(versions) == 0:
            time.sleep(5)
            continue
        version = random.choice(versions)
        print('Reader initing run to read: ', version)
        with wandb.init(reinit=True, job_type='reader') as run:
            run.use_artifact(version)
            print('Reader downloading: ', version)
            version.download('read-%s' % reader_id)
            print('Reader verifying: ', version)
            version.verify('read-%s' % reader_id)
            print('Reader verified: ', version)

def proc_cache_garbage_collector(stop_queue, cache_gc_period_max):
    while True:
        try:
            stop_queue.get_nowait()
            print('GC stopping')
            return
        except queue.Empty:
            pass
        time.sleep(random.randrange(cache_gc_period_max))
        print('Cache GC')
        os.system('rm -rf ~/.cache/wandb/artifacts')

def proc_version_deleter(stop_queue, artifact_name, min_versions, delete_period_max):
    api = wandb.Api()
    while True:
        versions = api.artifact_versions('dataset', artifact_name)
        versions = [v for v in versions if v.state == 'COMMITTED']
        if len(versions) > min_versions:
            version = random.choice(versions)
            print('Delete version', version)
            # TODO: implement delete
        time.sleep(random.randrange(delete_period_max))

def proc_bucket_garbage_collector(stop_queue, bucket_gc_period_max):
    while True:
        time.sleep(random.randrange(cache_gc_period_max))
        print('Bucket GC')
        # TODO: implement bucket gc

def main(argv):
    print('Load test starting')
    args = parser.parse_args()

    # set global entity and project before chdir'ing
    from wandb.apis import InternalApi
    api = InternalApi()
    os.environ['WANDB_ENTITY'] = api.settings('entity')
    os.environ['WANDB_PROJECT'] = api.settings('project')
    os.environ['WANDB_BASE_URL'] = api.settings('base_url')

    # Change dir to avoid litering code directory
    tempdir = tempfile.TemporaryDirectory()
    os.chdir(tempdir.name)

    artifact_name = 'load-artifact-' + ''.join(
        random.choices(string.ascii_lowercase + string.digits, k=10))

    print('Generating source data')
    source_file_names = gen_files(
        args.gen_n_files, args.gen_max_small_size, args.gen_max_large_size)
    print('Done generating source data')

    procs = []
    stop_queue = multiprocessing.Queue()

    # start all processes

    # writers
    for i in range(args.num_writers):
        p = multiprocessing.Process(
            target=proc_version_writer,
            args=(
                stop_queue,
                source_file_names,
                artifact_name,
                args.files_per_version_min,
                args.files_per_version_max))
        p.start()
        procs.append(p)

    # readers
    for i in range(args.num_readers):
        p = multiprocessing.Process(
            target=proc_version_reader,
            args=(
                stop_queue,
                artifact_name,
                i))
        p.start()
        procs.append(p)

    # cache garbage collector
    if args.cache_gc_period_max is None:
        print('Testing cache GC process not enabled!')
    else:
        p = multiprocessing.Process(
            target=proc_cache_garbage_collector,
            args=(
                stop_queue,
                args.cache_gc_period_max))
        p.start()
        procs.append(p)

    # test phase
    time.sleep(args.test_phase_seconds)

    print('Test phase time expired')

    # stop all processes and wait til all are done
    for i in range(len(procs)):
        stop_queue.put(True)
    print('Waiting for processes to stop')
    for proc in procs:
        proc.join()
        if proc.exitcode != 0:
            print('FAIL! Test phase failed')
            sys.exit(1)

    print('Test phase successfully completed')

    print('Starting verification phase')
    
    api = wandb.Api()
    versions = api.artifact_versions('dataset', artifact_name)
    for v in versions:
        # TODO: allow deleted once we build deletion support
        if v.state != 'COMMITTED':
            print('FAIL! Artifact version not committed: %s' % v)
            sys.exit(1)
    
    print('Verification succeeded')

if __name__ == '__main__':
    main(sys.argv)