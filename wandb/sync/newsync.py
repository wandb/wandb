__all__ = ["SyncManager"]

import asyncio
from collections import defaultdict, deque
import concurrent.futures
import datetime
import heapq
from itertools import cycle, islice
import multiprocessing as mp
import os
import pathlib
import psutil
import tempfile
import threading
import time
from typing import Any, Dict, List, Iterable, Optional, Tuple, Union
import sys

import wandb
from wandb.proto import wandb_internal_pb2
from wandb.sdk.internal import datastore
from wandb.util import check_and_warn_old


WANDB_SUFFIX = ".wandb"
SYNCED_SUFFIX = ".synced"
TMPDIR = tempfile.TemporaryDirectory()


TOTAL_MEMORY = psutil.virtual_memory().total
# convert to MB?
MAX_MEMORY = 0.1
# MAX_MEMORY = 0.001
MAX_HEAP_SIZE = 100_000  # max number of items in the heaps


def get_n_cpu():
    """
    Returns the number of CPUs on the system.
    """
    if hasattr(os, "sched_getaffinity"):
        return len(os.sched_getaffinity(0))
    return mp.cpu_count()


# N_CPU = get_n_cpu()
N_CPU = 4


def roundrobin(*iterables):
    """
    Merge multiple iterables into a single iterable
    roundrobin('ABC', 'D', 'EF') --> A D E B F C
    """
    # Recipe credited to George Sakkis
    pending = len(iterables)
    next_items = cycle(iter(it).__next__ for it in iterables)
    while pending:
        try:
            for next_item in next_items:
                yield next_item()
        except StopIteration:
            pending -= 1
            next_items = cycle(islice(next_items, pending))


def split_into_chunks(
    data: Iterable[Any],
    chunk_size: int = 100,
    round_robin: bool = False,
) -> List[List[Any]]:
    """
    Split a list of records into chunks of size chunk_size.
    """
    if not isinstance(data, list):
        data = list(data)

    def make_chunks(_data: List[Any]) -> List[List[Any]]:
        return [_data[i:i + chunk_size] for i in range(0, len(_data), chunk_size)]

    chunked_data = make_chunks(data)
    if not round_robin:
        return chunked_data
    data = list(roundrobin(*chunked_data))
    return make_chunks(data)


def init_queue(queue: mp.Queue) -> None:
    """
    Initialize the queue like this to ensure both fork and spawn start methods work.
    """
    globals()["results_queue"] = queue


def parse_protobuf(data: bytes) -> Tuple[str, wandb_internal_pb2.Record]:
    protobuf = wandb_internal_pb2.Record()
    protobuf.ParseFromString(data)
    record_type = protobuf.WhichOneof("record_type")

    # what is your talent, Pedro? Magic!

    return record_type, protobuf
    # return None


def process_data(sync_item: str, data: Dict[str, Union[int, List[dict]]]) -> None:
    """
    Deserialize a list of records and add it to the results queue.
    """
    chunk_number: int = data["chunk_number"]
    chunk: List[dict] = data["chunk"]
    # results = []
    results_queue: mp.Queue = globals()["results_queue"]
    for item in chunk:
        record_type, protobuf = parse_protobuf(item["record"])
        if True:
            short_run_id = sync_item.split('-')[-1].split('.wandb')[0]
            # print(
            #     f"run_id: {short_run_id}, chunk: {chunk_number}, "
            #     f"item: {item['record_number']} finished"
            # )
        # print(id(globals()["results_queue"]))
        # results.append(
        #     (sync_item, item["record_number"], record_type, protobuf)
        # )
        results_queue.put(
            (sync_item, item["record_number"], record_type, protobuf)
        )
    # for result in results:
    #     results_queue.put(result)


class SyncManager:
    def __init__(
        self,
        sync_items: List[str],
        project: Optional[str] = None,
        entity: Optional[str] = None,
        run_id: Optional[str] = None,
        mark_synced: bool = True,
        app_url: str = wandb.Settings().base_url,
        view: bool = False,
        verbose: bool = False,
        live: bool = False,
        max_memory: float = MAX_MEMORY,
    ):

        self._live = live  # todo: implement live sync mode
        self.sync_items = sync_items
        self._project = project
        self._entity = entity
        self._run_id = run_id
        self._mark_synced = mark_synced
        self._app_url = app_url
        self._view = view
        self._verbose = verbose

        # store tasks in deque per "sync item" (i.e. run)
        self.tasks: Dict[str, deque] = defaultdict(deque)
        # store the (unsorted) results in a global multiprocessing queue
        self.results_queue = mp.Queue()
        # print(id(self.results_queue))
        # use heaps to ensure sequential order of results, per "item" (run)
        self.result_heaps: Dict[str, list] = defaultdict(list)
        # sequential number of the most-recently-processed chunk, per "item" (run)
        self.current_chunk_number: Dict[str, int] = defaultdict(lambda: -1)
        # track memory usage of each ("run_id", "task_id") pair
        self.memory_usage: Dict[Tuple[str, int], int] = defaultdict(int)
        # track total memory usage
        self.total_memory = 0
        # maximum memory usage
        self.max_memory = max_memory * TOTAL_MEMORY

        self.sleep_time: float = 0.5

        self.running: bool = True
        # FIXME: turn these into an asyncio task once SyncManager is async
        self.dumper = threading.Thread(target=self._dump)
        self.dumper.start()

        if self._verbose:
            print("Hello from the shiny new SyncManager!")

    def _robust_scan(self, ds):
        """Attempt to scan data, handling incomplete files"""
        try:
            return ds.scan_data()
        except AssertionError as e:
            if ds.in_last_block() and not self._live:
                wandb.termwarn(
                    f".wandb file is incomplete ({e}), "
                    "be sure to sync this run again once it's finished or run"
                )
                return None
            else:
                raise e

    async def _process_tasks(
        self,
        executor: concurrent.futures.ProcessPoolExecutor,
        run_id: str,
    ) -> None:
        """
        Submit tasks to the executor, taking memory usage into account.
        """
        while self.tasks[run_id]:
            # before submitting a task to the executor, ensure that
            # the memory usage of the currently running tasks is not too high
            # and the size of the heap with the results is not too large
            chunk_memory = self.tasks[run_id][0]["chunk_memory"]
            if not (
                    self.total_memory + chunk_memory <= self.max_memory
                    # and len(self.result_heaps[run_id]) <= MAX_HEAP_SIZE
            ):
                if self._verbose:
                    print(
                        f"{run_id}: too much memory pressure, waiting... "
                        f"[tasks left: {len(self.tasks[run_id])}]"
                    )
                await asyncio.sleep(self.sleep_time)
                continue
            chunk = self.tasks[run_id].popleft()
            self.total_memory += chunk["chunk_memory"]
            for item in chunk["chunk"]:
                # store memory usage of each ("run_id", "task_id") pair
                self.memory_usage[(run_id, item["record_number"])] = item["memory"]

            if self._verbose:
                print(
                    datetime.datetime.now(),
                    f"run_id: {run_id}; total_memory: {self.total_memory}"
                )
            executor.submit(
                process_data,
                run_id,
                chunk,
            )

    async def _watch(self) -> None:
        """
        Watch the tasks and the results and decide when to stop
        """
        while self.running:
            if self._verbose:
                print("watcher is running")
            if (
                # more tasks to schedule?
                any([len(self.tasks[task]) for task in self.tasks])
                # any tasks running?
                or self.memory_usage
                # any results to dump?
                or any([len(heap) for heap in self.result_heaps.values()])
            ):
                await asyncio.sleep(self.sleep_time)
                continue
            print("All tasks finished, shutting down")
            print(self.memory_usage, self.total_memory)
            print(self.result_heaps)
            self.running = False

    async def _harvest(self) -> None:
        """
        Get results from the global multiprocessing queue and put them into the heaps.
        """
        while self.running:
            if self._verbose:
                print("harvester is running")
            if not self.results_queue.empty():
                result = self.results_queue.get()
                # run id:
                run_id = result[0]
                # if True:
                async with asyncio.Lock():
                    heapq.heappush(self.result_heaps[run_id], result[1:])
                    # run_id, task_id
                    key = (run_id, result[1])
                    self.total_memory -= self.memory_usage[key]
                    del self.memory_usage[key]
                    if self._verbose:
                        pass
                        # print(f"harvester got result: {result}; total_memory: {self.total_memory}")
                        print(f"harvester got result for: {key}; total_memory: {self.total_memory}")
                        print(f"heap min: {self.result_heaps[run_id][0][0]}")
            else:
                await asyncio.sleep(self.sleep_time)

    def _dump(self) -> None:
        """
        Dump results from the heaps respecting the order of the tasks.
        Wait for the corresponding <self.current_chunk_number>-th result
        to become available and dump it.

        TODO: using threading for now because SendManager is not async-friendly yet.
        """
        while self.running:
            if (
                not any(
                    len(self.result_heaps[run_id])
                    and self.result_heaps[run_id][0][0] == self.current_chunk_number[run_id] + 1
                    for run_id in self.tasks
                )
            ):
                time.sleep(self.sleep_time)
                continue

            for run_id in self.tasks:
                if self._verbose:
                    print(f"dumper is running for {run_id.split('-')[-1].split('.wandb')[0]}")

                has_data_to_dump = (
                    len(self.result_heaps[run_id])
                    and self.result_heaps[run_id][0][0] == self.current_chunk_number[run_id] + 1
                )

                if not has_data_to_dump:
                    # if self._verbose and self.result_heaps[task_name]:
                    if len(self.result_heaps[run_id]):
                        print(
                            "dumper waiting for data to dump: "
                            f"{self.result_heaps[run_id][0][0]} {self.current_chunk_number[run_id] + 1}"
                        )
                    continue

                with threading.Lock():
                    chunk = heapq.heappop(self.result_heaps[run_id])
                    if self._verbose:
                        pass
                    short_run_id = run_id.split('-')[-1].split('.wandb')[0]
                    print(
                        f"dumper posted result: {short_run_id}: "
                        f"chunk {chunk[0]}: {chunk[1]} {datetime.datetime.now()}\n"
                    )
                    self.current_chunk_number[run_id] += 1
                    if self._verbose:
                        pass
                        # print(f"dumper posted result: {task_name}/{chunk}")

    async def async_run(
        self,
        executor: concurrent.futures.ProcessPoolExecutor,
    ) -> None:
        """
        Map tasks to the executor, harvest and dump results.
        """
        async_tasks = []
        # schedule async task per wandb run to be synced
        for run_id in self.tasks.keys():
            task = asyncio.create_task(self._process_tasks(executor, run_id))
            async_tasks.append(task)

        async_tasks.append(asyncio.create_task(self._watch()))
        async_tasks.append(asyncio.create_task(self._harvest()))
        # async_tasks.append(asyncio.create_task(self._dump()))

        # await asyncio.gather(*async_tasks)
        await asyncio.wait(async_tasks)

    def run(self, n_cpu: int = N_CPU) -> None:
        """
        Generate tasks and run them in parallel.
        """
        for sync_item in self.sync_items:
            # if self._verbose:
            print(f"Generating tasks for: {sync_item}")
            sync_item_path = pathlib.Path(sync_item)
            # input(">")
            if sync_item_path.is_dir():
                files = list(map(str, sync_item_path.glob("**/*")))
                filtered_files = list(filter(lambda f: f.endswith(WANDB_SUFFIX), files))
                if check_and_warn_old(files) or len(filtered_files) != 1:
                    print(f"Skipping directory: {sync_item}")
                    continue
                if len(filtered_files) > 0:
                    sync_item = str(sync_item_path / filtered_files[0])

            root_dir = str(sync_item_path.parent)
            # sm = sender.SendManager.setup(root_dir)

            ds = datastore.DataStore()
            try:
                ds.open_for_scan(sync_item)
            except AssertionError as e:
                print(f"`.wandb` file is empty ({e}), skipping: {sync_item}")
                return None

            # scan .wandb files and generate tasks
            record_number = 0
            tic = time.time()
            while True:
                record = self._robust_scan(ds)
                if record is None:
                    break
                self.tasks[sync_item].append(
                    {
                        "sync_item": sync_item,
                        "record_number": record_number,
                        "record": record,
                        "memory": sys.getsizeof(record),
                    }
                )
                # parse_protobuf(record)
                record_number += 1
                if self._verbose:
                    print("extracted record:", record_number)
            if self._verbose:
                print(
                    "\n",
                    [len(self.tasks[task_name]) for task_name in self.tasks.keys()],
                    time.time() - tic
                )

            # chunk tasks, number the resulting chunks, and track memory usage per chunk
            chunk_size = int(len(self.tasks[sync_item]) / n_cpu)
            # chunk_size = 100
            # todo: ? fill chunks with consecutive tasks, i.e.
            #  [0, 3, 6] [1, 4, 7] [2, 5]
            #  or just shuffle? turns out, not much difference :(
            chunked_tasks = [
                {
                    "chunk_number": chunk_number,
                    "chunk": chunk,
                    "chunk_memory": sum([task["memory"] for task in chunk]),
                }
                for chunk_number, chunk
                in enumerate(split_into_chunks(self.tasks[sync_item], chunk_size))
            ]
            self.tasks[sync_item] = deque(chunked_tasks)

            # print total memory usage in megabytes
            total_memory = sum([task['chunk_memory'] for task in chunked_tasks])
            print(
                f"memory: {sync_item}: {total_memory / 1024 / 1024} MB"
            )

        print("\n", [{task_name: len(self.tasks[task_name])} for task_name in self.tasks.keys()])
        input("\n>")

        # concurrent.futures will manage the task queue for us under the hood
        with concurrent.futures.ProcessPoolExecutor(
            max_workers=n_cpu,
            initializer=init_queue,
            initargs=(self.results_queue, ),
        ) as executor:
            try:
                asyncio.run(self.async_run(executor))
            except KeyboardInterrupt:
                self.running = False
                print("Keyboard interrupt caught, stopping...")
                print(list(self.result_heaps.keys()))
                print(self.total_memory)

            finally:
                self.running = False

        print("Done!")
