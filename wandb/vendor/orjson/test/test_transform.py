# SPDX-License-Identifier: (Apache-2.0 OR MIT)
# Copyright ijl (2019-2025)

import pytest

import orjson

from .util import needs_data, read_fixture_bytes


def _read_file(filename):
    return read_fixture_bytes(filename, "transform").strip(b"\n").strip(b"\r")


@needs_data
class TestJSONTestSuiteTransform:
    def _pass_transform(self, filename, reference=None):
        data = _read_file(filename)
        assert orjson.dumps(orjson.loads(data)) == (reference or data)

    def _fail_transform(self, filename):
        data = _read_file(filename)
        with pytest.raises(orjson.JSONDecodeError):
            orjson.loads(data)

    def test_number_1(self):
        """
        number_1.0.json
        """
        self._pass_transform("number_1.0.json")

    def test_number_1e6(self):
        """
        number_1e6.json
        """
        self._pass_transform("number_1e6.json", b"[1000000.0]")

    def test_number_1e_999(self):
        """
        number_1e-999.json
        """
        self._pass_transform("number_1e-999.json", b"[0.0]")

    def test_number_10000000000000000999(self):
        """
        number_10000000000000000999.json
        """
        # cannot serialize due to range
        assert orjson.loads(_read_file("number_10000000000000000999.json")) == [
            10000000000000000999,
        ]

    def test_number_1000000000000000(self):
        """
        number_1000000000000000.json
        """
        self._pass_transform("number_1000000000000000.json")

    def test_object_key_nfc_nfd(self):
        """
        object_key_nfc_nfd.json
        """
        self._pass_transform("object_key_nfc_nfd.json")

    def test_object_key_nfd_nfc(self):
        """
        object_key_nfd_nfc.json
        """
        self._pass_transform("object_key_nfd_nfc.json")

    def test_object_same_key_different_values(self):
        """
        object_same_key_different_values.json
        """
        self._pass_transform("object_same_key_different_values.json", b'{"a":2}')

    def test_object_same_key_same_value(self):
        """
        object_same_key_same_value.json
        """
        self._pass_transform("object_same_key_same_value.json", b'{"a":1}')

    def test_object_same_key_unclear_values(self):
        """
        object_same_key_unclear_values.json
        """
        data = _read_file("object_same_key_unclear_values.json")
        # varies by backend
        assert data in (b'{"a":-0.0}', b'{"a":0, "a":-0}')

    def test_string_1_escaped_invalid_codepoint(self):
        """
        string_1_escaped_invalid_codepoint.json
        """
        self._fail_transform("string_1_escaped_invalid_codepoint.json")

    def test_string_1_invalid_codepoint(self):
        """
        string_1_invalid_codepoint.json
        """
        self._fail_transform("string_1_invalid_codepoint.json")

    def test_string_2_escaped_invalid_codepoints(self):
        """
        string_2_escaped_invalid_codepoints.json
        """
        self._fail_transform("string_2_escaped_invalid_codepoints.json")

    def test_string_2_invalid_codepoints(self):
        """
        string_2_invalid_codepoints.json
        """
        self._fail_transform("string_2_invalid_codepoints.json")

    def test_string_3_escaped_invalid_codepoints(self):
        """
        string_3_escaped_invalid_codepoints.json
        """
        self._fail_transform("string_3_escaped_invalid_codepoints.json")

    def test_string_3_invalid_codepoints(self):
        """
        string_3_invalid_codepoints.json
        """
        self._fail_transform("string_3_invalid_codepoints.json")

    def test_string_with_escaped_NULL(self):
        """
        string_with_escaped_NULL.json
        """
        self._pass_transform("string_with_escaped_NULL.json")
