"""Table matching wandb.Table API with streaming/append support."""

import atexit
import os
import queue
import random
import string
import threading
import time

import wandb
from wandb import data_types

# This controls the maximum (expected) number of rows per partition. There is a tradeoff:
# - If this number is too small, we will have too many partitions, which can slow down read time and impact performance.
# - If this number is too large, we will end up duplicating data on upload, which can impact performance of the writing client,
MAX_PARTITION_SIZE = 100


# This timeout schedule controls how often we flush data to the server. For the most realtime experience, we want to flush
# as often as possible. However, this is costly on the client & wastes many cycles uploading duplicate data. From a data
# reading perspective, we want to minimize the number of partitions, so we want to flush as infrequently as possible.
def next_flush_timeout(cur_time, start_time, cur_flush_timeout):
    if cur_time - start_time < 5 * 60:
        # First 5 minutes, flush every second
        max_flush_timeout = 1
    elif cur_time - start_time < 60 * 60:
        # First hour, flush every 60 seconds
        max_flush_timeout = 60
    else:
        # Flush every 10 minutes
        max_flush_timeout = 600
    return min(cur_flush_timeout * 2, max_flush_timeout)


def random_string(n):
    return "".join(random.choices(string.ascii_lowercase, k=n))


def get_cur_files(run, name):
    try:
        api = wandb.Api(overrides={"entity": run.entity, "project": run.project_name()})
        cur_art = api.artifact(name + ":latest", type="table")
    except wandb.errors.CommError:
        return
    cur_art.download(name)


def save_partition(run, name, art_name, columns, partition_name, partition_rows):
    new_art = wandb.Artifact(art_name, type="stream_table")
    new_art.add_dir(
        "/tmp/wandb/stream_table/" + art_name + "/partitions", name="partitions"
    )
    table = wandb.Table(columns=columns)
    for row in partition_rows:
        table.add_data(*row)
    new_art.add(table, name="partitions/" + partition_name)
    part_table = data_types.PartitionedTable("partitions")
    new_art.add(part_table, name="partitions")
    new_art.save()
    new_art.wait()
    run.log({name: part_table})


def stream_table_thread(name, columns, row_queue):
    run = wandb.run or wandb.init()
    art_name = f"run-st-{run.id}-{name}"

    os.makedirs("/tmp/wandb/stream_table/" + art_name + "/partitions", exist_ok=True)
    get_cur_files(run, art_name)

    partition_rows = []
    flush_timeout = 1
    start_time = time.time()
    partition_name = "partition-%s" % random_string(10)
    last_flush_time = time.time()
    while True:
        try:
            row = row_queue.get(timeout=1)
            if row is None:
                break
            partition_rows.append(row)
        except queue.Empty:
            pass
        timestamp = time.time()
        if partition_rows and timestamp - last_flush_time > flush_timeout:
            # This is waits for the artifact to be saved, which can take a while
            save_partition(run, name, art_name, columns, partition_name, partition_rows)
            last_flush_time = time.time()
            flush_timeout = next_flush_timeout(timestamp, start_time, flush_timeout)
            if len(partition_rows) > MAX_PARTITION_SIZE:
                get_cur_files(run, art_name)
                partition_name = "partition-%s" % random_string(10)
                partition_rows = []
    if partition_rows:
        save_partition(run, name, art_name, columns, partition_name, partition_rows)


class StreamTable:
    """Table matching wandb.Table API with streaming/append support."""

    def __init__(self, name, columns):
        self.columns = columns
        self.row_queue = queue.Queue()
        self.flush_thread = threading.Thread(
            target=stream_table_thread, args=(name, columns, self.row_queue)
        )
        self.flush_thread.start()
        atexit.register(self.join)

    def join(self):
        self.row_queue.put(None)
        self.flush_thread.join()

    def add_data(self, *args):
        self.row_queue.put(args)
