# SPDX-License-Identifier: (Apache-2.0 OR MIT)
# Copyright ijl (2020-2026), Aarni Koskela (2021)

from json import loads as json_loads

import pytest

from .data import FIXTURE_AS_OBJECTS, FIXTURE_NAMES, LIBRARIES


@pytest.mark.parametrize("library", LIBRARIES)
@pytest.mark.parametrize("fixture", FIXTURE_NAMES)
def test_dumps(benchmark, fixture, library):
    dumper, _ = LIBRARIES[library]
    benchmark.group = f"{fixture} serialization"
    benchmark.extra_info["lib"] = library
    data = FIXTURE_AS_OBJECTS[fixture]
    benchmark.extra_info["correct"] = json_loads(dumper(data)) == data  # type: ignore
    benchmark(dumper, data)
