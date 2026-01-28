# SPDX-License-Identifier: (Apache-2.0 OR MIT)
# Copyright ijl (2019-2022)

import orjson


class TestCanonicalTests:
    def test_dumps_ctrl_escape(self):
        """
        dumps() ctrl characters
        """
        assert orjson.dumps("text\u0003\r\n") == b'"text\\u0003\\r\\n"'

    def test_dumps_escape_quote_backslash(self):
        """
        dumps() quote, backslash escape
        """
        assert orjson.dumps(r'"\ test') == b'"\\"\\\\ test"'

    def test_dumps_escape_line_separator(self):
        """
        dumps() U+2028, U+2029 escape
        """
        assert (
            orjson.dumps({"spaces": "\u2028 \u2029"})
            == b'{"spaces":"\xe2\x80\xa8 \xe2\x80\xa9"}'
        )
