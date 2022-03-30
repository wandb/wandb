from collections import deque
import concurrent.futures
import heapq
import multiprocessing as mp
import numpy as np
import os
import sys
import threading
import time

# fix numpy seed
np.random.seed(0)

MAX_MEMORY = 400
MAX_HEAP_SIZE = 2


def init_queue(queue: mp.Queue):
    """
    Initialize the queue like this to ensure both fork and spawn start methods work.
    """
    globals()["results_queue"] = queue


def svd_of_random_matrix(i: int, n: int = 10):
    """
    Generate a random matrix and compute its SVD a bunch of times
    to simulate a task with high-CPU usage.
    """
    a = np.random.rand(n, n)
    u, s, v = np.linalg.svd(a)
    for _ in range(100_000):
        u, s, v = np.linalg.svd(a)
    print(f"task {i} finished")
    # print(id(globals()["results_queue"]))
    # return i, u, s, v
    globals()["results_queue"].put((i, v[0][0]))


class Manager:
    def __init__(self):
        self.tasks = deque()
        self.results_queue = mp.Queue()
        # print(id(self.results_queue))
        self.results_heap = []
        self.current_chunk_number = -1
        # track memory usage of each task
        self.memory_usage = dict()
        # track total memory usage
        self.total_memory = 0

        self.sleep_time = 0.5

        self.running = True
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
                heapq.heappush(self.results_heap, result)
                self.total_memory -= self.memory_usage[result[0]]
                del self.memory_usage[result[0]]
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
            if self.results_heap and self.results_heap[0][0] == self.current_chunk_number + 1:
                chunk = heapq.heappop(self.results_heap)
                with open("junk020.log", "a") as f:
                    f.write(f"chunk {chunk[0]}: {chunk[1]}\n")
                self.current_chunk_number += 1
                print(f"dumper posted result: {chunk}")
            else:
                time.sleep(self.sleep_time)

    def run(self):
        """
        Generate tasks and run them in parallel.
        """
        for i in range(10):
            # simulate different memory usage per task
            self.tasks.append({"i": i, "n": 10, "mem": np.random.randint(1, 100)})

        # concurrent.futures will manage the task queue for us under the hood
        with concurrent.futures.ProcessPoolExecutor(
            max_workers=2,
            initializer=init_queue,
            initargs=(self.results_queue, ),
        ) as executor:
            while self.tasks:
                try:
                    # before submitting a task to the executor, ensure that
                    # the memory usage of the currently running tasks is not too high
                    # and the size of the heap with the results is not too large
                    if (
                        self.total_memory + self.tasks[0]["mem"] <= MAX_MEMORY
                        and len(self.results_heap) <= MAX_HEAP_SIZE
                    ):
                        task = self.tasks.popleft()
                        self.total_memory += task["mem"]
                        self.memory_usage[task["i"]] = task["mem"]
                        print(f"task: {task}; total_memory: {self.total_memory}")
                        # executor.submit(svd_of_random_matrix, task["i"], task["n"])
                        executor.submit(
                            svd_of_random_matrix,
                            task["i"],
                            task["n"],
                        )
                    else:
                        print("too much memory pressure, waiting...")
                        time.sleep(self.sleep_time)
                except KeyboardInterrupt:
                    self.running = False
                    break

        if not self.running:
            # KeyboardInterrupt was caught, exit
            sys.exit(1)

        while self.memory_usage or self.results_heap:
            print("waiting for final results to arrive and get dumped...")
            time.sleep(self.sleep_time)

        self.running = False
        print(self.memory_usage, self.total_memory)
        print(self.results_heap)


if __name__ == "__main__":
    # start_method = "spawn"
    start_method = "fork"
    mp.set_start_method(method=start_method)
    m = Manager()
    m.run()
