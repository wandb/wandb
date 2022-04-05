__all__ = ["SyncManager"]

import asyncio
from collections import defaultdict, deque
import concurrent.futures
import datetime
import heapq
from itertools import zip_longest
import multiprocessing as mp
import os
import pathlib
import psutil
import tempfile
import threading
import time
from typing import Dict, List, Optional, Tuple
import sys

import wandb
from wandb.proto import wandb_internal_pb2
from wandb.sdk.internal import datastore
from wandb.util import check_and_warn_old


WANDB_SUFFIX = ".wandb"
SYNCED_SUFFIX = ".synced"
TMPDIR = tempfile.TemporaryDirectory()


TOTAL_MEMORY = psutil.virtual_memory().total
MAX_MEMORY = 0.2
MAX_HEAP_SIZE = 1000  # max number of items in the heaps


def get_n_cpu():
    """
    Returns the number of CPUs on the system.
    """
    if hasattr(os, "sched_getaffinity"):
        return len(os.sched_getaffinity(0))
    return mp.cpu_count()


# N_CPU = get_n_cpu()
N_CPU = 1


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


def process_record(i: int, item: str, data: bytes) -> None:
    """
    Deserialize a record of data and add it to the results queue.
    """
    record_type, protobuf = parse_protobuf(data)
    if True:
        print(f"item {item.split('-')[-1].split('.wandb')[0]} task {i} finished")
    # print(id(globals()["results_queue"]))
    globals()["results_queue"].put((item, i, record_type, protobuf))


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
        self.dumpers: List[threading.Thread] = []

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
        task_name: str,
    ) -> None:
        """
        Submit tasks to the executor, taking memory usage into account.
        """
        while self.tasks[task_name]:
            # before submitting a task to the executor, ensure that
            # the memory usage of the currently running tasks is not too high
            # and the size of the heap with the results is not too large
            if not (
                self.total_memory + self.tasks[task_name][0]["mem"] <= self.max_memory
                and len(self.result_heaps[task_name]) <= MAX_HEAP_SIZE
            ):
                if self._verbose:
                    print(
                        f"{task_name}: too much memory pressure, waiting... "
                        f"[tasks left: {len(self.tasks[task_name])}]"
                    )
                await asyncio.sleep(self.sleep_time)
                continue
            task_item = self.tasks[task_name].popleft()
            self.total_memory += task_item["mem"]
            self.memory_usage[(task_name, task_item["record_number"])] = task_item["mem"]
            if self._verbose:
                print(
                    datetime.datetime.now(),
                    f"task: {task_name}/{task_item}; total_memory: {self.total_memory}"
                )
            executor.submit(
                process_record,
                task_item["record_number"],
                task_name,
                task_item["record"],
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
                item = result[0]
                # if True:
                async with asyncio.Lock():
                    heapq.heappush(self.result_heaps[item], result[1:])
                    # run_id, task_id
                    key = (item, result[1])
                    self.total_memory -= self.memory_usage[key]
                    del self.memory_usage[key]
                    if self._verbose:
                        print(f"harvester got result: {result}; total_memory: {self.total_memory}")
            else:
                await asyncio.sleep(self.sleep_time)

    def _dump(self, task_name: str) -> None:
        """
        Dump results from the heaps respecting the order of the tasks.
        Wait for the corresponding <self.current_chunk_number>-th result
        to become available and dump it.

        TODO: using threading for now because SendManager is not async-friendly yet.
        """
        while self.running:
            if self._verbose:
                print(f"dumper is running for {task_name.split('-')[-1].split('.wandb')[0]}")

            if not self.result_heaps[task_name]:
                time.sleep(self.sleep_time)
                continue

            if (
                self.result_heaps[task_name]
                and self.result_heaps[task_name][0][0] == self.current_chunk_number[task_name] + 1
            ):
                with threading.Lock():
                    chunk = heapq.heappop(self.result_heaps[task_name])
                    if self._verbose:
                        print(f"{task_name}: chunk {chunk[0]}: {chunk[1]} {datetime.datetime.now()}\n")
                    self.current_chunk_number[task_name] += 1
                    if self._verbose:
                        print(f"dumper posted result: {task_name}/{chunk}")

    async def async_run(
        self,
        executor: concurrent.futures.ProcessPoolExecutor,
    ) -> None:
        """
        Map tasks to the executor, harvest and dump results.
        """
        async_tasks = []
        # schedule async task per run
        for task_name in self.tasks.keys():
            task = asyncio.create_task(self._process_tasks(executor, task_name))
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
            if self._verbose:
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
                print(f".wandb file is empty ({e}), skipping: {sync_item}")
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
                        "mem": sys.getsizeof(record),
                    }
                )
                # parse_protobuf(record)
                record_number += 1
                print("parsed record:", record_number)
            if self._verbose:
                print(
                    "\n",
                    [len(self.tasks[task_name]) for task_name in self.tasks.keys()],
                    time.time() - tic
                )

            # chunk tasks
            # chunk_size = int(len(self.tasks[sync_item]) / n_cpu)
            # chunk_size = 100
            # self.tasks[sync_item] = deque(list(
            #     zip_longest(*[iter(self.tasks[sync_item])] * chunk_size, fillvalue='')
            # ))

            # create a dump thread for each task
            self.dumpers.append(
                threading.Thread(target=self._dump, args=(sync_item,))
            )
            self.dumpers[-1].start()

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
