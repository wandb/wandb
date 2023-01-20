import itertools
import os
import random
import string
from dataclasses import dataclass

from wandb import util
from wandb.sdk.internal.file_stream import CRDedupeFilePolicy
from wandb.sdk.lib.file_stream_utils import split_files


@dataclass
class Chunk:
    data: str = None


def test_split_files():
    def choices(pop, k=1):
        # Note: random.choices was added in python 3.6
        return [random.choice(pop) for _ in range(k)]

    def rand_string_list(size):
        width = max(1, int(size / 10))
        num_lines = int(size / width)
        return [
            "".join(
                choices(
                    string.ascii_letters
                    + string.punctuation
                    + string.digits
                    + string.whitespace,
                    k=random.randint(1, width),
                )
            )
            for _ in range(num_lines)
        ]

    file_size = 1  # MB
    num_files = 10
    chunk_size = 0.1  # MB
    files = {
        "file_%s.txt"
        % i: {"content": rand_string_list(int(file_size * 1024 * 1024)), "offset": 0}
        for i in range(num_files)
    }
    chunks = list(split_files(files, max_bytes=chunk_size * 1024 * 1024))

    # re-combine chunks
    buff = {}
    for c in chunks:
        for k, v in c.items():
            if k in buff:
                buff[k].append(v)
            else:
                buff[k] = [v]
    files2 = {
        k: {
            "content": list(
                itertools.chain(
                    *(c["content"] for c in sorted(v, key=lambda c: c["offset"]))
                )
            ),
            "offset": 0,
        }
        for k, v in buff.items()
    }
    assert files == files2

    # Verify chunk offsets (These can be messed up and above assertion would still pass).
    for fname in files:
        offset_size_pairs = [
            (c[fname]["offset"], len(c[fname]["content"])) for c in chunks if fname in c
        ]
        offset_size_pairs.sort(key=lambda p: p[0])
        assert offset_size_pairs[0][0] == 0
        for i in range(len(offset_size_pairs) - 1):
            assert offset_size_pairs[i + 1][0] == sum(offset_size_pairs[i])
        assert sum(offset_size_pairs[-1]) == len(files[fname]["content"])


def test_crdedupe_consecutive_offsets():
    fp = CRDedupeFilePolicy()
    console = {1: "a", 2: "a", 3: "a", 8: "a", 12: "a", 13: "a", 30: "a"}
    intervals = fp.get_consecutive_offsets(console)
    print(intervals)
    assert intervals == [[1, 3], [8, 8], [12, 13], [30, 30]]


def test_crdedupe_split_chunk():
    fp = CRDedupeFilePolicy()
    answer = [
        ("2020-08-25T20:38:36.895321 ", "this is my line of text\nsecond line\n"),
        ("ERROR 2020-08-25T20:38:36.895321 ", "this is my line of text\nsecond line\n"),
    ]
    test_data = [
        "2020-08-25T20:38:36.895321 this is my line of text\nsecond line\n",
        "ERROR 2020-08-25T20:38:36.895321 this is my line of text\nsecond line\n",
    ]
    for i, data in enumerate(test_data):
        c = Chunk(data=data)
        prefix, rest = fp.split_chunk(c)
        assert prefix == answer[i][0]
        assert rest == answer[i][1]


def test_crdedupe_process_chunks():
    fp = CRDedupeFilePolicy()
    sep = os.linesep
    files = {"output.log": None}

    # Test STDERR progress bar updates (\r lines) overwrite the correct offset.
    # Test STDOUT and STDERR normal messages get appended correctly.
    chunks = [
        Chunk(data=f"timestamp text{sep}"),
        Chunk(data=f"ERROR timestamp error message{sep}"),
        Chunk(data=f"ERROR timestamp progress bar{sep}"),
        Chunk(data=f"ERROR timestamp \rprogress bar update 1{sep}"),
        Chunk(data=f"ERROR timestamp \rprogress bar update 2{sep}"),
        Chunk(data=f"timestamp text{sep}text{sep}text{sep}"),
        Chunk(data=f"ERROR timestamp error message{sep}"),
    ]
    ret = fp.process_chunks(chunks)
    want = [
        {
            "offset": 0,
            "content": [
                "timestamp text\n",
                "ERROR timestamp error message\n",
                "ERROR timestamp progress bar update 2\n",
                "timestamp text\n",
                "timestamp text\n",
                "timestamp text\n",
                "ERROR timestamp error message\n",
            ],
        }
    ]
    print(f"\n{ret}")
    print(want)
    assert ret == want
    files["output.log"] = ret
    file_requests = list(split_files(files, max_bytes=util.MAX_LINE_BYTES))
    assert 1 == len(file_requests)

    # Test that STDERR progress bar updates in next list of chunks still
    # maps to the correct offset.
    # Test that we can handle STDOUT progress bars (\r lines) as well.
    chunks = [
        Chunk(data=f"ERROR timestamp \rprogress bar update 3{sep}"),
        Chunk(data=f"ERROR timestamp \rprogress bar update 4{sep}"),
        Chunk(data=f"timestamp \rstdout progress bar{sep}"),
        Chunk(data=f"timestamp text{sep}"),
        Chunk(data=f"timestamp \rstdout progress bar update{sep}"),
    ]
    ret = fp.process_chunks(chunks)
    want = [
        {"offset": 2, "content": ["ERROR timestamp progress bar update 4\n"]},
        {"offset": 5, "content": ["timestamp stdout progress bar update\n"]},
        {"offset": 7, "content": ["timestamp text\n"]},
    ]
    print(f"\n{ret}")
    print(want)
    assert ret == want
    files["output.log"] = ret
    file_requests = list(split_files(files, max_bytes=util.MAX_LINE_BYTES))
    assert 3 == len(file_requests)

    # Test that code handles final progress bar output and correctly
    # offsets any new progress bars.
    chunks = [
        Chunk(data=f"timestamp text{sep}"),
        Chunk(data=f"ERROR timestamp \rprogress bar final{sep}text{sep}text{sep}"),
        Chunk(data=f"ERROR timestamp error message{sep}"),
        Chunk(data=f"ERROR timestamp new progress bar{sep}"),
        Chunk(data=f"ERROR timestamp \rnew progress bar update 1{sep}"),
    ]
    ret = fp.process_chunks(chunks)
    want = [
        {"offset": 2, "content": ["ERROR timestamp progress bar final\n"]},
        {
            "offset": 8,
            "content": [
                "timestamp text\n",
                "ERROR timestamp text\n",
                "ERROR timestamp text\n",
                "ERROR timestamp error message\n",
                "ERROR timestamp new progress bar update 1\n",
            ],
        },
    ]
    print(f"\n{ret}")
    print(want)
    assert ret == want
    files["output.log"] = ret
    file_requests = list(split_files(files, max_bytes=util.MAX_LINE_BYTES))
    assert 2 == len(file_requests)
