#!/usr/bin/env python

import csv
import dataclasses
import time
from typing import List, Optional


@dataclasses.dataclass(frozen=True)
class FunctionTiming:
    function_name: str
    runtime_seconds: float


def timeit(
    timings: List[FunctionTiming],
):
    """Timing decorator.

    Args:
       timings: list of FunctionTiming to append for each function call
    """

    def timing_func(func):
        def wrapper(*args, **kwargs):
            t1 = time.time()
            result = func(*args, **kwargs)
            t2 = time.time()
            timings.append(FunctionTiming(func.__name__, (t2 - t1)))
            return result

        return wrapper

    return timing_func


def write(
    fname: str,
    timings: List[FunctionTiming],
    prefix_list: Optional[List] = None,
):
    """Appends timing data to the file.

    Args:
        fname: The name of the timing data output file which is appended
        timings: The timings data to append to the file, one row per timing.
            This list is cleared at the end.
        prefix_list: An optional prefix for each timing line written.
    """
    prefix_list = prefix_list or []
    with open(fname, "a") as csvfile:
        writer = csv.writer(csvfile)
        for item in timings:
            writer.writerow(prefix_list + [item.function_name, item.runtime_seconds])
    timings.clear()
