#!/usr/bin/env python

import csv
import time


def timeit(lst):
    def timing_val(func):
        def wrapper(*args, **kwargs):
            t1 = time.time()
            result = func(*args, **kwargs)
            t2 = time.time()
            lst.append((func.__name__, (t2 - t1)))
            return result

        return wrapper

    return timing_val


def write(
    fname: str,
    timings: <timing type>,
    prefix: str | None = None,
):
    """Appends timing data to the file.
    
    Args:
        fname: The name of the file.
        timings: The timings data to append to the file, one row per timing.
            This list is cleared at the end.
        prefix: An optional prefix for each timing line written.
    """
    prefix = prefix or []
    with open(fname, "a") as csvfile:
        writer = csv.writer(csvfile)
        for item in lst:
            writer.writerow(prefix + list(item))
    lst.clear()
