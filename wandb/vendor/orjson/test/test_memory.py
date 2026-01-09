# SPDX-License-Identifier: (Apache-2.0 OR MIT)
# Copyright ijl (2019-2025), Rami Chowdhury (2020)

import dataclasses
import datetime
import gc
import random

from .util import numpy, pandas

try:
    import pytz
except ImportError:
    pytz = None  # type: ignore

try:
    import psutil
except ImportError:
    psutil = None  # type: ignore

import pytest

import orjson

from .util import IS_FREETHREADING

FIXTURE = '{"a":[81891289, 8919812.190129012], "b": false, "c": null, "d": "東京"}'


def default(obj):
    return str(obj)


@dataclasses.dataclass
class Member:
    id: int
    active: bool


@dataclasses.dataclass
class Object:
    id: int
    updated_at: datetime.datetime
    name: str
    members: list[Member]


DATACLASS_FIXTURE = [
    Object(
        i,
        datetime.datetime.now(datetime.timezone.utc)
        + datetime.timedelta(seconds=random.randint(0, 10000)),
        str(i) * 3,
        [Member(j, True) for j in range(10)],
    )
    for i in range(100000, 101000)
]

MAX_INCREASE = 4194304  # 4MiB

if IS_FREETHREADING:
    MAX_INCREASE *= 4


class Unsupported:
    pass


class TestMemory:
    @pytest.mark.skipif(psutil is None, reason="psutil not installed")
    def test_memory_loads(self):
        """
        loads() memory leak
        """
        proc = psutil.Process()
        gc.collect()
        val = orjson.loads(FIXTURE)
        assert val
        mem = proc.memory_info().rss
        for _ in range(10000):
            val = orjson.loads(FIXTURE)
            assert val
        gc.collect()
        assert proc.memory_info().rss <= mem + MAX_INCREASE

    @pytest.mark.skipif(psutil is None, reason="psutil not installed")
    def test_memory_loads_memoryview(self):
        """
        loads() memory leak using memoryview
        """
        proc = psutil.Process()
        gc.collect()
        fixture = FIXTURE.encode("utf-8")
        val = orjson.loads(fixture)
        assert val
        mem = proc.memory_info().rss
        for _ in range(10000):
            val = orjson.loads(memoryview(fixture))
            assert val
        gc.collect()
        assert proc.memory_info().rss <= mem + MAX_INCREASE

    @pytest.mark.skipif(psutil is None, reason="psutil not installed")
    def test_memory_dumps(self):
        """
        dumps() memory leak
        """
        proc = psutil.Process()
        gc.collect()
        fixture = orjson.loads(FIXTURE)
        val = orjson.dumps(fixture)
        assert val
        mem = proc.memory_info().rss
        for _ in range(10000):
            val = orjson.dumps(fixture)
            assert val
        gc.collect()
        assert proc.memory_info().rss <= mem + MAX_INCREASE
        assert proc.memory_info().rss <= mem + MAX_INCREASE

    @pytest.mark.skipif(psutil is None, reason="psutil not installed")
    def test_memory_loads_exc(self):
        """
        loads() memory leak exception without a GC pause
        """
        proc = psutil.Process()
        gc.disable()
        mem = proc.memory_info().rss
        n = 10000
        i = 0
        for _ in range(n):
            try:
                orjson.loads("")
            except orjson.JSONDecodeError:
                i += 1
        assert n == i
        assert proc.memory_info().rss <= mem + MAX_INCREASE
        gc.enable()

    @pytest.mark.skipif(psutil is None, reason="psutil not installed")
    def test_memory_dumps_exc(self):
        """
        dumps() memory leak exception without a GC pause
        """
        proc = psutil.Process()
        gc.disable()
        data = Unsupported()
        mem = proc.memory_info().rss
        n = 10000
        i = 0
        for _ in range(n):
            try:
                orjson.dumps(data)
            except orjson.JSONEncodeError:
                i += 1
        assert n == i
        assert proc.memory_info().rss <= mem + MAX_INCREASE
        gc.enable()

    @pytest.mark.skipif(psutil is None, reason="psutil not installed")
    def test_memory_dumps_default(self):
        """
        dumps() default memory leak
        """
        proc = psutil.Process()
        gc.collect()
        fixture = orjson.loads(FIXTURE)

        class Custom:
            def __init__(self, name):
                self.name = name

            def __str__(self):
                return f"{self.__class__.__name__}({self.name})"

        fixture["custom"] = Custom("orjson")
        val = orjson.dumps(fixture, default=default)
        mem = proc.memory_info().rss
        for _ in range(10000):
            val = orjson.dumps(fixture, default=default)
            assert val
        gc.collect()
        assert proc.memory_info().rss <= mem + MAX_INCREASE

    @pytest.mark.skipif(psutil is None, reason="psutil not installed")
    def test_memory_dumps_dataclass(self):
        """
        dumps() dataclass memory leak
        """
        proc = psutil.Process()
        gc.collect()
        val = orjson.dumps(DATACLASS_FIXTURE)
        assert val
        mem = proc.memory_info().rss
        for _ in range(100):
            val = orjson.dumps(DATACLASS_FIXTURE)
            assert val
        assert val
        gc.collect()
        assert proc.memory_info().rss <= mem + MAX_INCREASE

    @pytest.mark.skipif(
        psutil is None or pytz is None,
        reason="psutil not installed",
    )
    def test_memory_dumps_pytz_tzinfo(self):
        """
        dumps() pytz tzinfo memory leak
        """
        proc = psutil.Process()
        gc.collect()
        dt = datetime.datetime.now()
        val = orjson.dumps(pytz.UTC.localize(dt))
        assert val
        mem = proc.memory_info().rss
        for _ in range(50000):
            val = orjson.dumps(pytz.UTC.localize(dt))
            assert val
        assert val
        gc.collect()
        assert proc.memory_info().rss <= mem + MAX_INCREASE

    @pytest.mark.skipif(psutil is None, reason="psutil not installed")
    def test_memory_loads_keys(self):
        """
        loads() memory leak with number of keys causing cache eviction
        """
        proc = psutil.Process()
        gc.collect()
        fixture = {f"key_{idx}": "value" for idx in range(1024)}
        assert len(fixture) == 1024
        val = orjson.dumps(fixture)
        loaded = orjson.loads(val)
        assert loaded
        mem = proc.memory_info().rss
        for _ in range(100):
            loaded = orjson.loads(val)
            assert loaded
        gc.collect()
        assert proc.memory_info().rss <= mem + MAX_INCREASE

    @pytest.mark.skipif(psutil is None, reason="psutil not installed")
    @pytest.mark.skipif(numpy is None, reason="numpy is not installed")
    def test_memory_dumps_numpy(self):
        """
        dumps() numpy memory leak
        """
        proc = psutil.Process()
        gc.collect()
        fixture = numpy.random.rand(4, 4, 4)  # type: ignore
        val = orjson.dumps(fixture, option=orjson.OPT_SERIALIZE_NUMPY)
        assert val
        mem = proc.memory_info().rss
        for _ in range(100):
            val = orjson.dumps(fixture, option=orjson.OPT_SERIALIZE_NUMPY)
            assert val
        assert val
        gc.collect()
        assert proc.memory_info().rss <= mem + MAX_INCREASE

    @pytest.mark.skipif(psutil is None, reason="psutil not installed")
    @pytest.mark.skipif(pandas is None, reason="pandas is not installed")
    def test_memory_dumps_pandas(self):
        """
        dumps() pandas memory leak
        """
        proc = psutil.Process()
        gc.collect()
        numpy.random.rand(4, 4, 4)  # type: ignore
        df = pandas.Series(numpy.random.rand(4, 4, 4).tolist())  # type: ignore
        val = df.map(orjson.dumps)
        assert not val.empty
        mem = proc.memory_info().rss
        for _ in range(100):
            val = df.map(orjson.dumps)
            assert not val.empty
        gc.collect()
        assert proc.memory_info().rss <= mem + MAX_INCREASE

    @pytest.mark.skipif(psutil is None, reason="psutil not installed")
    def test_memory_dumps_fragment(self):
        """
        dumps() Fragment memory leak
        """
        proc = psutil.Process()
        gc.collect()
        orjson.dumps(orjson.Fragment(str(0)))
        mem = proc.memory_info().rss
        for i in range(10000):
            orjson.dumps(orjson.Fragment(str(i)))
        gc.collect()
        assert proc.memory_info().rss <= mem + MAX_INCREASE
