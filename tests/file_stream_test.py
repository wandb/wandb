import itertools
import random
import string
import sys

import wandb

PY3 = sys.version_info.major == 3 and sys.version_info.minor >= 6
if PY3:
    from wandb.sdk.lib.file_stream_utils import split_files
else:
    from wandb.sdk_py27.lib.file_stream_utils import split_files


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
