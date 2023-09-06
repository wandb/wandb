"""sample."""

import math


class UniformSampleAccumulator:
    def __init__(self, min_samples=None):
        self._samples = min_samples or 64
        # force power of 2 samples
        self._samples = 2 ** int(math.ceil(math.log(self._samples, 2)))
        # target oversample by factor of 2
        self._samples2 = self._samples * 2
        # max size of each buffer
        self._max = self._samples2 // 2
        self._shift = 0
        self._mask = (1 << self._shift) - 1
        self._buckets = int(math.log(self._samples2, 2))
        self._buckets_bits = int(math.log(self._buckets, 2))
        self._buckets_mask = (1 << self._buckets_bits + 1) - 1
        self._buckets_index = 0
        self._bucket = []
        self._index = [0] * self._buckets
        self._count = 0
        self._log2 = [0]

        # pre-allocate buckets
        for _ in range(self._buckets):
            self._bucket.append([0] * self._max)
        # compute integer log2
        self._log2 += [int(math.log(i, 2)) for i in range(1, 2**self._buckets + 1)]

    def _show(self):
        print("=" * 20)
        for b in range(self._buckets):
            b = (b + self._buckets_index) % self._buckets
            vals = [self._bucket[b][i] for i in range(self._index[b])]
            print(f"{b}: {vals}")

    def add(self, val):
        self._count += 1
        cnt = self._count
        if cnt & self._mask:
            return
        b = cnt >> self._shift
        b = self._log2[b]  # b = int(math.log(b, 2))
        if b >= self._buckets:
            self._index[self._buckets_index] = 0
            self._buckets_index = (self._buckets_index + 1) % self._buckets
            self._shift += 1
            self._mask = (self._mask << 1) | 1
            b += self._buckets - 1
        b = (b + self._buckets_index) % self._buckets
        self._bucket[b][self._index[b]] = val
        self._index[b] += 1

    def get(self):
        full = []
        sampled = []
        # self._show()
        for b in range(self._buckets):
            max_num = 2**b
            b = (b + self._buckets_index) % self._buckets
            modb = self._index[b] // max_num
            for i in range(self._index[b]):
                if not modb or i % modb == 0:
                    sampled.append(self._bucket[b][i])
                full.append(self._bucket[b][i])
        if len(sampled) < self._samples:
            return tuple(full)
        return tuple(sampled)
