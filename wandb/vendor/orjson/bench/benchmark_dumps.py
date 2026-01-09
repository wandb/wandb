# SPDX-License-Identifier: (Apache-2.0 OR MIT)
# Copyright Aarni Koskela (2021), ijl (2022-2025)

from json import loads as json_loads

import pytest

from .data import fixtures, libraries
from .util import read_fixture_obj


@pytest.mark.parametrize("library", libraries)
@pytest.mark.parametrize("fixture", fixtures)
def test_dumps(benchmark, fixture, library):
    dumper, _ = libraries[library]
    benchmark.group = f"{fixture} serialization"
    benchmark.extra_info["lib"] = library
    data = read_fixture_obj(f"{fixture}.xz")
    benchmark.extra_info["correct"] = json_loads(dumper(data)) == data  # type: ignore
    benchmark(dumper, data)
