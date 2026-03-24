# SPDX-License-Identifier: (Apache-2.0 OR MIT)
# Copyright ijl (2020-2026), Aarni Koskela (2021)

from json import loads as json_loads

import pytest

from .data import FIXTURE_AS_BYTES, FIXTURE_NAMES, LIBRARIES


@pytest.mark.parametrize("fixture", FIXTURE_NAMES)
@pytest.mark.parametrize("library", LIBRARIES)
def test_loads(benchmark, fixture, library):
    dumper, loader = LIBRARIES[library]
    benchmark.group = f"{fixture} deserialization"
    benchmark.extra_info["lib"] = library
    data = FIXTURE_AS_BYTES[fixture]
    correct = json_loads(dumper(loader(data))) == json_loads(data)  # type: ignore
    benchmark.extra_info["correct"] = correct
    benchmark(loader, data)
