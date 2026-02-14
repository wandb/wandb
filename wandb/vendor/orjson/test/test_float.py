# SPDX-License-Identifier: (Apache-2.0 OR MIT)

import orjson
import pytest
import numpy as np

class TestFloat:
    @pytest.mark.parametrize("value", [
        float('nan'),
        float('infinity'),
        float('-infinity'),
        np.nan,
        np.inf,
        np.NINF
    ])
    def test_dumps_succeeds_on_invalid_float_without_option(self, value):
        """
        dumps() succeeds on invalid floats (NaN, Infinity, -Infinity),
        without option OPT_FAIL_ON_INVALID_FLOAT
        """
        res = orjson.dumps(value)
        assert res == b'null'

    @pytest.mark.parametrize("value", [
        float('nan'),
        float('infinity'),
        float('-infinity'),
        np.nan,
        np.inf,
        np.NINF
    ])
    def test_dumps_fails_on_invalid_float_with_option(self, value):
        """
        dumps() fails with JSONEncodeError on invalid floats (NaN, Infinity, -Infinity),
        with option OPT_FAIL_ON_INVALID_FLOAT
        """
        with pytest.raises(orjson.JSONEncodeError):
            orjson.dumps(float('nan'), option=orjson.OPT_FAIL_ON_INVALID_FLOAT)