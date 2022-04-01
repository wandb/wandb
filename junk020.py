import asyncio
from collections import defaultdict, deque
import concurrent.futures
import datetime
import heapq
from itertools import cycle, islice
import multiprocessing as mp
import numpy as np
import sys
import threading
import time
from typing import Dict, Tuple

# fix numpy seed
np.random.seed(0)

MAX_MEMORY = 400
MAX_HEAP_SIZE = 2


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


def minus_one():
    return -1


def init_queue(queue: mp.Queue):
    """
    Initialize the queue like this to ensure both fork and spawn start methods work.
    """
    globals()["results_queue"] = queue


def svd_of_random_matrix(i: int, item: str, n: int = 10):
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
    def __init__(self):
        # store tasks in deque per item (i.e. run)
        self.tasks: Dict[str, deque] = defaultdict(deque)
        # store the (unsorted) results in a global multiprocessing queue
        self.results_queue = mp.Queue()
        # print(id(self.results_queue))
        # use heaps to ensure sequential order of results
        self.result_heaps: Dict[str, list] = defaultdict(list)
        # sequential number of the most-recently-processed chunk
        self.current_chunk_number: Dict[str, int] = defaultdict(minus_one)
        # track memory usage of each (task, item) pair
        self.memory_usage: Dict[Tuple[str, int], int] = defaultdict(int)
        # track total memory usage
        self.total_memory = 0

        self.sleep_time: float = 0.5

        self.running: bool = True
        self.harvester = threading.Thread(target=self.get_results)
        self.dumper = threading.Thread(target=self.post_results)
        self.harvester.start()
        self.dumper.start()

    def get_results(self):
        """
        Get results from the global multiprocessing queue and put them into the heap
        """
        while self.running:
            print("harvester is running")
            if not self.results_queue.empty():
                result = self.results_queue.get()
                item = result[0]
                heapq.heappush(self.result_heaps[item], result[1:])
                key = (item, result[1])
                self.total_memory -= self.memory_usage[key]
                del self.memory_usage[key]
                print(f"harvester got result: {result}; total_memory: {self.total_memory}")
            else:
                time.sleep(self.sleep_time)

    def post_results(self):
        """
        Dump results from the heap respecting the order of the tasks.
        Wait for the <self.current_chunk_number>-th result to become available and dump it.
        """
        while self.running:
            print("dumper is running")

            if not any(self.result_heaps[item] for item in self.tasks):
                time.sleep(self.sleep_time)
                continue

            for item in self.tasks:
                if (
                    self.result_heaps[item]
                    and self.result_heaps[item][0][0] == self.current_chunk_number[item] + 1
                ):
                    chunk = heapq.heappop(self.result_heaps[item])
                    with open(f"{item}.log", "a") as f:
                        f.write(f"chunk {chunk[0]}: {chunk[1]}\n")
                    self.current_chunk_number[item] += 1
                    print(f"dumper posted result: {item}/{chunk}")

    async def process_tasks(self, executor, task_name):
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

    # asynchronously iterate over multiple lists one element at a time
    async def schedule_tasks(
        self,
        executor: concurrent.futures.ProcessPoolExecutor,
        tasks: Dict[str, deque],
    ):
        async_tasks = []
        for task_name in tasks.keys():
            task = asyncio.create_task(self.process_tasks(executor, task_name))
            async_tasks.append(task)
        await asyncio.gather(*async_tasks)

    def run(self):
        """
        Generate tasks and run them in parallel.
        """
        # simulate a situation with multiple runs of different length to be synced,
        # with different memory usage per task within each run
        # tasks = defaultdict(deque)
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
        # self.tasks = deque(roundrobin(*tasks.values()))

        # concurrent.futures will manage the task queue for us under the hood
        with concurrent.futures.ProcessPoolExecutor(
            max_workers=2,
            initializer=init_queue,
            initargs=(self.results_queue, ),
        ) as executor:
            try:
                asyncio.run(self.schedule_tasks(executor, self.tasks))
            except KeyboardInterrupt:
                self.running = False
                print("Keyboard interrupt caught, stopping...")

        if not self.running:
            # KeyboardInterrupt was caught, exit
            sys.exit(1)

        while self.memory_usage or any([heap for heap in self.result_heaps.values()]):
            print("waiting for final results to arrive and get dumped...")
            time.sleep(self.sleep_time)

        self.running = False
        print(self.memory_usage, self.total_memory)
        print(self.result_heaps)


if __name__ == "__main__":
    start_method = "spawn"
    # start_method = "fork"
    mp.set_start_method(method=start_method)
    m = Manager()
    m.run()
