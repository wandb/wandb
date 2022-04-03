import aiofiles
import asyncio
from collections import defaultdict, deque
import concurrent.futures
import datetime
import heapq
from itertools import cycle, islice
import multiprocessing as mp
import numpy as np
import os
from typing import Dict, Tuple

# fix numpy seed
np.random.seed(0)

MAX_MEMORY = 400
MAX_HEAP_SIZE = 2


def get_n_cpu():
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


def init_queue(queue: mp.Queue) -> None:
    """
    Initialize the queue like this to ensure both fork and spawn start methods work.
    """
    globals()["results_queue"] = queue


def svd_of_random_matrix(i: int, item: str, n: int = 10) -> None:
    """
    Generate a random matrix and compute its SVD a bunch of times
    to simulate a task with high-CPU usage.
    """
    a = np.random.rand(n, n)
    u, s, v = np.linalg.svd(a)
    for _ in range(100_000):
        u, s, v = np.linalg.svd(a)
    print(f"item {item} task {i} finished")
    # print(id(globals()["results_queue"]))
    # return i, u, s, v
    globals()["results_queue"].put((item, i, v[0][0]))


class Manager:
    def __init__(self) -> None:
        # store tasks in deque per "item" (i.e. run)
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

        self.sleep_time: float = 0.5

        self.running: bool = True

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
                self.total_memory + self.tasks[task_name][0]["mem"] <= MAX_MEMORY
                and len(self.result_heaps[task_name]) <= MAX_HEAP_SIZE
            ):
                print(
                    f"{task_name}: too much memory pressure, waiting... "
                    f"[tasks left: {len(self.tasks[task_name])}]"
                )
                await asyncio.sleep(self.sleep_time)
                continue
            task_item = self.tasks[task_name].popleft()
            self.total_memory += task_item["mem"]
            self.memory_usage[(task_name, task_item["i"])] = task_item["mem"]
            print(
                datetime.datetime.now(),
                f"task: {task_name}/{task_item}; total_memory: {self.total_memory}"
            )
            executor.submit(
                svd_of_random_matrix,
                task_item["i"],
                task_name,
                task_item["n"],
            )

    async def _watch(self) -> None:
        """
        Watch the tasks and the results and decide when to stop
        """
        while self.running:
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
            print("harvester is running")
            if not self.results_queue.empty():
                result = self.results_queue.get()
                # run id:
                item = result[0]
                async with asyncio.Lock():
                    heapq.heappush(self.result_heaps[item], result[1:])
                    # run_id, task_id
                    key = (item, result[1])
                    self.total_memory -= self.memory_usage[key]
                    del self.memory_usage[key]
                    print(f"harvester got result: {result}; total_memory: {self.total_memory}")
            else:
                await asyncio.sleep(self.sleep_time)

    async def _dump(self) -> None:
        """
        Dump results from the heaps respecting the order of the tasks.
        Wait for the corresponding <self.current_chunk_number>-th result
        to become available and dump it.
        """
        while self.running:
            print("dumper is running")

            if not any(self.result_heaps[item] for item in self.tasks):
                await asyncio.sleep(self.sleep_time)
                continue

            for item in self.tasks:
                if (
                    self.result_heaps[item]
                    and self.result_heaps[item][0][0] == self.current_chunk_number[item] + 1
                ):
                    async with asyncio.Lock():
                        chunk = heapq.heappop(self.result_heaps[item])
                    # with open(f"{item}.log", "a") as f:
                    #     f.write(f"chunk {chunk[0]}: {chunk[1]} {datetime.datetime.now()}\n")
                    async with aiofiles.open(f"{item}.log", "a") as f:
                        await f.write(f"chunk {chunk[0]}: {chunk[1]} {datetime.datetime.now()}\n")
                    self.current_chunk_number[item] += 1
                    print(f"dumper posted result: {item}/{chunk}")

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
        async_tasks.append(asyncio.create_task(self._dump()))

        # await asyncio.gather(*async_tasks)
        await asyncio.wait(async_tasks)

    def run(self, n_cpu: int = N_CPU) -> None:
        """
        Generate tasks and run them in parallel.
        """
        # simulate a situation with multiple runs of different length to be synced,
        # with different memory usage per task within each run
        for name, n_tasks, matrix_size, (lower_memory, upper_memory) in [
            ("run_1", 10, 10, (1, 100)),
            ("run_2", 5, 20, (20, 200)),
            ("run_3", 7, 8, (1, 60)),
        ]:
            for i in range(n_tasks):
                self.tasks[name].append(
                    {
                        "name": name,
                        "i": i,
                        "n": matrix_size,
                        "mem": np.random.randint(lower_memory, upper_memory)
                    }
                )

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


if __name__ == "__main__":
    # start_method = "spawn"
    start_method = "fork"
    mp.set_start_method(method=start_method)
    m = Manager()
    m.run()
