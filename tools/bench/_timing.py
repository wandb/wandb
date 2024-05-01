#!/usr/bin/env python

import time
import csv


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


def write(fname, lst, prefix=None):
    prefix = prefix or []
    with open(fname, "a") as csvfile:
        writer = csv.writer(csvfile)
        for item in lst:
            writer.writerow(prefix + list(item))
    lst.clear()
