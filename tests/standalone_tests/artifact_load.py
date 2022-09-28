"""Artifact load test.

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
import multiprocessing
import os
import queue
import random
import string
import sys
import tempfile
import time
from collections import defaultdict
from datetime import datetime

import wandb
from tqdm import tqdm

parser = argparse.ArgumentParser(description="artifacts load test")

# if unspecified, we create a new project for testdata
parser.add_argument("--project", type=str, default=None)

# gen file args
parser.add_argument(
    "--gen_n_files", type=int, required=True, help="Path to dataset directory"
)
parser.add_argument("--gen_max_small_size", type=int, required=True)
parser.add_argument("--gen_max_large_size", type=int, required=True)

parser.add_argument("--test_phase_seconds", type=int, required=True)

# writer args
parser.add_argument("--num_writers", type=int, required=True)
parser.add_argument("--files_per_version_min", type=int, required=True)
parser.add_argument("--files_per_version_max", type=int, required=True)
parser.add_argument("--non_overlapping_writers", default=True, action="store_true")
parser.add_argument("--distributed_fanout", type=int, default=1)
parser.add_argument("--blocking", type=bool, default=False)

# reader args
parser.add_argument("--num_readers", type=int, required=True)

# deleter args
parser.add_argument("--num_deleters", type=int, default=0)
parser.add_argument("--min_versions_before_delete", type=int, default=2)
parser.add_argument("--delete_period_max", type=int, default=10)

# cache garbage collector args
parser.add_argument("--cache_gc_period_max", type=int)


def gen_files(n_files, max_small_size, max_large_size):
    bufsize = max_large_size * 100

    # create a random buffer to pull from. drawing ranges from this buffer is
    # orders of magnitude faster than creating random contents for each file.
    buf = "".join(random.choices(string.ascii_uppercase + string.digits, k=bufsize))

    fnames = []
    for i in tqdm(range(n_files)):
        full_dir = os.path.join("source_files", "%s" % (i % 4))
        os.makedirs(full_dir, exist_ok=True)
        fname = os.path.join(full_dir, "%s.txt" % i)
        fnames.append(fname)
        with open(fname, "w") as f:
            small = random.random() < 0.5
            if small:
                size = int(random.random() * max_small_size)
            else:
                size = int(random.random() * max_large_size)
            start_pos = int(random.random() * (bufsize - size))
            f.write(buf[start_pos : start_pos + size])

    return fnames


def proc_version_writer(
    stop_queue,
    stats_queue,
    project_name,
    fnames,
    artifact_name,
    files_per_version_min,
    files_per_version_max,
    blocking,
):
    while True:
        try:
            stop_queue.get_nowait()
            print("Writer stopping")
            return
        except queue.Empty:
            pass
        print("Writer initing run")
        with wandb.init(reinit=True, project=project_name, job_type="writer") as run:
            files_in_version = random.randrange(
                files_per_version_min, files_per_version_max
            )
            version_fnames = random.sample(fnames, files_in_version)
            art = wandb.Artifact(artifact_name, type="dataset")
            for version_fname in version_fnames:
                art.add_file(version_fname)
            run.log_artifact(art)

            if blocking:
                art.wait()
                assert art.version is not None
            stats_queue.put(
                {"write_artifact_count": 1, "write_total_files": files_in_version}
            )


def _train(chunk, artifact_name, project_name, group_name):
    with wandb.init(
        reinit=True, project=project_name, group=group_name, job_type="writer"
    ) as run:
        art = wandb.Artifact(artifact_name, type="dataset")
        for file in chunk:
            art.add_file(file)
        run.upsert_artifact(art)


def proc_version_writer_distributed(
    stop_queue,
    stats_queue,
    project_name,
    fnames,
    artifact_name,
    files_per_version_min,
    files_per_version_max,
    fanout,
    blocking,
):
    while True:
        try:
            stop_queue.get_nowait()
            print("Writer stopping")
            return
        except queue.Empty:
            pass
        print("Writer initing run")
        group_name = "".join(random.choice(string.ascii_uppercase) for _ in range(8))

        files_in_version = random.randrange(
            files_per_version_min, files_per_version_max
        )
        version_fnames = random.sample(fnames, files_in_version)
        chunk_size = max(int(len(version_fnames) / fanout), 1)
        chunks = [
            version_fnames[i : i + chunk_size]
            for i in range(0, len(version_fnames), chunk_size)
        ]

        # TODO: Once we resolve issues with spawn or switch to fork, we can run these in separate processes
        # instead of running them serially.
        for i in range(fanout):
            _train(chunks[i], artifact_name, project_name, group_name)

        with wandb.init(
            reinit=True, project=project_name, group=group_name, job_type="writer"
        ) as run:
            print(f"Committing {group_name}")
            art = wandb.Artifact(artifact_name, type="dataset")
            run.finish_artifact(art)
            stats_queue.put(
                {"write_artifact_count": 1, "write_total_files": files_in_version}
            )


def proc_version_reader(
    stop_queue, stats_queue, project_name, artifact_name, reader_id
):
    api = wandb.Api()
    # initial sleep to ensure we've created the sequence. Public API fails
    # with a nasty error if not.
    time.sleep(10)
    while True:
        try:
            stop_queue.get_nowait()
            print("Reader stopping")
            return
        except queue.Empty:
            pass
        versions = api.artifact_versions("dataset", artifact_name)
        versions = [v for v in versions if v.state == "COMMITTED"]
        if len(versions) == 0:
            time.sleep(5)
            continue
        version = random.choice(versions)
        print("Reader initing run to read: ", version)
        stats_queue.put({"read_artifact_count": 1})
        with wandb.init(reinit=True, project=project_name, job_type="reader") as run:
            try:
                run.use_artifact(version)
            except Exception as e:
                stats_queue.put({"read_use_error": 1})
                print(f"Reader caught error on use_artifact: {e}")
                updated_version = api.artifact(version.name)
                if updated_version.state != "DELETED":
                    raise Exception(
                        "Artifact exception caught but artifact not DELETED"
                    )
                continue
            print("Reader downloading: ", version)
            try:
                version.checkout("read-%s" % reader_id)
            except Exception as e:
                stats_queue.put({"read_download_error": 1})
                print(f"Reader caught error on version.download: {e}")
                updated_version = api.artifact(version.name)
                if updated_version.state != "DELETED":
                    raise Exception(
                        "Artifact exception caught but artifact not DELETED"
                    )
                continue
            print("Reader verifying: ", version)
            version.verify(f"read-{reader_id}")
            print("Reader verified: ", version)


def proc_version_deleter(
    stop_queue, stats_queue, artifact_name, min_versions, delete_period_max
):
    api = wandb.Api()
    # initial sleep to ensure we've created the sequence. Public API fails
    # with a nasty error if not.
    time.sleep(10)
    while True:
        try:
            stop_queue.get_nowait()
            print("Deleter stopping")
            return
        except queue.Empty:
            pass
        versions = api.artifact_versions("dataset", artifact_name)
        # Don't try to delete versions that have aliases, the backend won't allow it
        versions = [
            v for v in versions if v.state == "COMMITTED" and len(v.aliases) == 0
        ]
        if len(versions) > min_versions:
            version = random.choice(versions)
            print("Delete version", version)
            stats_queue.put({"delete_count": 1})
            start_time = time.time()
            version.delete()
            stats_queue.put({"delete_total_time": time.time() - start_time})
            print("Delete version complete", version)
        time.sleep(random.randrange(delete_period_max))


def proc_cache_garbage_collector(stop_queue, cache_gc_period_max):
    while True:
        try:
            stop_queue.get_nowait()
            print("GC stopping")
            return
        except queue.Empty:
            pass
        time.sleep(random.randrange(cache_gc_period_max))
        print("Cache GC")
        os.system("rm -rf ~/.cache/wandb/artifacts")


def proc_bucket_garbage_collector(stop_queue, bucket_gc_period_max):
    while True:
        time.sleep(random.randrange(bucket_gc_period_max))
        print("Bucket GC")
        # TODO: implement bucket gc


def main(argv):  # noqa: C901
    args = parser.parse_args()
    print("Load test starting")

    project_name = args.project
    if project_name is None:
        project_name = "artifacts-load-test-%s" % str(datetime.now()).replace(
            " ", "-"
        ).replace(":", "-").replace(".", "-")

    env_project = os.environ.get("WANDB_PROJECT")

    sweep_id = os.environ.get("WANDB_SWEEP_ID")
    if sweep_id:
        del os.environ["WANDB_SWEEP_ID"]
    wandb_config_paths = os.environ.get("WANDB_CONFIG_PATHS")
    if wandb_config_paths:
        del os.environ["WANDB_CONFIG_PATHS"]
    wandb_run_id = os.environ.get("WANDB_RUN_ID")
    if wandb_run_id:
        del os.environ["WANDB_RUN_ID"]

    # set global entity and project before chdir'ing
    from wandb.apis import InternalApi

    api = InternalApi()
    settings_entity = api.settings("entity")
    settings_base_url = api.settings("base_url")
    os.environ["WANDB_ENTITY"] = os.environ.get("LOAD_TEST_ENTITY") or settings_entity
    os.environ["WANDB_PROJECT"] = project_name
    os.environ["WANDB_BASE_URL"] = (
        os.environ.get("LOAD_TEST_BASE_URL") or settings_base_url
    )

    # Change dir to avoid littering code directory
    pwd = os.getcwd()
    tempdir = tempfile.TemporaryDirectory()
    os.chdir(tempdir.name)

    artifact_name = "load-artifact-" + "".join(
        random.choices(string.ascii_lowercase + string.digits, k=10)
    )

    print("Generating source data")
    source_file_names = gen_files(
        args.gen_n_files, args.gen_max_small_size, args.gen_max_large_size
    )
    print("Done generating source data")

    procs = []
    stop_queue = multiprocessing.Queue()
    stats_queue = multiprocessing.Queue()

    # start all processes

    # writers
    for i in range(args.num_writers):
        file_names = source_file_names
        if args.non_overlapping_writers:
            chunk_size = int(len(source_file_names) / args.num_writers)
            file_names = source_file_names[i * chunk_size : (i + 1) * chunk_size]
        if args.distributed_fanout > 1:
            p = multiprocessing.Process(
                target=proc_version_writer_distributed,
                args=(
                    stop_queue,
                    stats_queue,
                    project_name,
                    file_names,
                    artifact_name,
                    args.files_per_version_min,
                    args.files_per_version_max,
                    args.distributed_fanout,
                    args.blocking,
                ),
            )
        else:
            p = multiprocessing.Process(
                target=proc_version_writer,
                args=(
                    stop_queue,
                    stats_queue,
                    project_name,
                    file_names,
                    artifact_name,
                    args.files_per_version_min,
                    args.files_per_version_max,
                    args.blocking,
                ),
            )
        p.start()
        procs.append(p)

    # readers
    for i in range(args.num_readers):
        p = multiprocessing.Process(
            target=proc_version_reader,
            args=(stop_queue, stats_queue, project_name, artifact_name, i),
        )
        p.start()
        procs.append(p)

    # deleters
    for _ in range(args.num_deleters):
        p = multiprocessing.Process(
            target=proc_version_deleter,
            args=(
                stop_queue,
                stats_queue,
                artifact_name,
                args.min_versions_before_delete,
                args.delete_period_max,
            ),
        )
        p.start()
        procs.append(p)

    # cache garbage collector
    if args.cache_gc_period_max is None:
        print("Testing cache GC process not enabled!")
    else:
        p = multiprocessing.Process(
            target=proc_cache_garbage_collector,
            args=(stop_queue, args.cache_gc_period_max),
        )
        p.start()
        procs.append(p)

    # reset environment
    os.environ["WANDB_ENTITY"] = settings_entity
    os.environ["WANDB_BASE_URL"] = settings_base_url
    os.environ
    if env_project is None:
        del os.environ["WANDB_PROJECT"]
    else:
        os.environ["WANDB_PROJECT"] = env_project
    if sweep_id:
        os.environ["WANDB_SWEEP_ID"] = sweep_id
    if wandb_config_paths:
        os.environ["WANDB_CONFIG_PATHS"] = wandb_config_paths
    if wandb_run_id:
        os.environ["WANDB_RUN_ID"] = wandb_run_id
    # go back to original dir
    os.chdir(pwd)

    # test phase
    start_time = time.time()
    stats = defaultdict(int)

    run = wandb.init(job_type="main-test-phase")
    run.config.update(args)
    while time.time() - start_time < args.test_phase_seconds:
        stat_update = None
        try:
            stat_update = stats_queue.get(True, 5000)
        except queue.Empty:
            pass
        print("** Test time: %s" % (time.time() - start_time))
        if stat_update:
            for k, v in stat_update.items():
                stats[k] += v
        wandb.log(stats)

    print("Test phase time expired")
    # stop all processes and wait til all are done
    for _ in range(len(procs)):
        stop_queue.put(True)
    print("Waiting for processes to stop")
    fail = False
    for proc in procs:
        proc.join()
        if proc.exitcode != 0:
            print("FAIL! Test phase failed")
            fail = True
            sys.exit(1)

    # drain remaining stats
    while True:
        try:
            stat_update = stats_queue.get_nowait()
        except queue.Empty:
            break
        for k, v in stat_update.items():
            stats[k] += v

    print("Stats")
    import pprint

    pprint.pprint(dict(stats))

    if fail:
        print("FAIL! Test phase failed")
        sys.exit(1)
    else:
        print("Test phase successfully completed")

    print("Starting verification phase")

    os.environ["WANDB_ENTITY"] = os.environ.get("LOAD_TEST_ENTITY") or settings_entity
    os.environ["WANDB_PROJECT"] = project_name
    os.environ["WANDB_BASE_URL"] = (
        os.environ.get("LOAD_TEST_BASE_URL") or settings_base_url
    )
    data_api = wandb.Api()
    # we need list artifacts by walking runs, accessing via
    # project.artifactType.artifacts only returns committed artifacts
    for run in data_api.runs("{}/{}".format(api.settings("entity"), project_name)):
        for v in run.logged_artifacts():
            # TODO: allow deleted once we build deletion support
            if v.state != "COMMITTED" and v.state != "DELETED":
                print("FAIL! Artifact version not committed or deleted: %s" % v)
                sys.exit(1)

    print("Verification succeeded")


if __name__ == "__main__":
    main(sys.argv)
