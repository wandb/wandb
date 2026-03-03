# SPDX-License-Identifier: (Apache-2.0 OR MIT)
# Copyright ijl (2018-2022), Aarni Koskela (2021)

import lzma
import os
from pathlib import Path

dirname = os.path.join(os.path.dirname(__file__), "../data")

if hasattr(os, "sched_setaffinity"):
    os.sched_setaffinity(os.getpid(), {0, 1})


def read_fixture(filename: str) -> bytes:
    path = Path(dirname, filename)
    if path.suffix == ".xz":
        contents = lzma.decompress(path.read_bytes())
    else:
        contents = path.read_bytes()
    return contents
