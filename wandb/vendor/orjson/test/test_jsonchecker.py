# SPDX-License-Identifier: (Apache-2.0 OR MIT)
# Copyright ijl (2018-2025)
"""
Tests files from http://json.org/JSON_checker/
"""

import pytest

import orjson

from .util import needs_data, read_fixture_str

PATTERN_1 = '["JSON Test Pattern pass1",{"object with 1 member":["array with 1 element"]},{},[],-42,true,false,null,{"integer":1234567890,"real":-9876.54321,"e":1.23456789e-13,"E":1.23456789e34,"":2.3456789012e76,"zero":0,"one":1,"space":" ","quote":"\\"","backslash":"\\\\","controls":"\\b\\f\\n\\r\\t","slash":"/ & /","alpha":"abcdefghijklmnopqrstuvwyz","ALPHA":"ABCDEFGHIJKLMNOPQRSTUVWYZ","digit":"0123456789","0123456789":"digit","special":"`1~!@#$%^&*()_+-={\':[,]}|;.</>?","hex":"ģ䕧覫췯ꯍ\uef4a","true":true,"false":false,"null":null,"array":[],"object":{},"address":"50 St. James Street","url":"http://www.JSON.org/","comment":"// /* <!-- --","# -- --> */":" "," s p a c e d ":[1,2,3,4,5,6,7],"compact":[1,2,3,4,5,6,7],"jsontext":"{\\"object with 1 member\\":[\\"array with 1 element\\"]}","quotes":"&#34; \\" %22 0x22 034 &#x22;","/\\\\\\"쫾몾ꮘﳞ볚\uef4a\\b\\f\\n\\r\\t`1~!@#$%^&*()_+-=[]{}|;:\',./<>?":"A key can be any string"},0.5,98.6,99.44,1066,10.0,1.0,0.1,1.0,2.0,2.0,"rosebud"]'.encode()


@needs_data
class TestJsonChecker:
    def _run_fail_json(self, filename, exc=orjson.JSONDecodeError):
        data = read_fixture_str(filename, "jsonchecker")
        pytest.raises(exc, orjson.loads, data)

    def _run_pass_json(self, filename, match=""):
        data = read_fixture_str(filename, "jsonchecker")
        assert orjson.dumps(orjson.loads(data)) == match

    def test_fail01(self):
        """
        fail01.json
        """
        self._run_pass_json(
            "fail01.json",
            b'"A JSON payload should be an object or array, not a string."',
        )

    def test_fail02(self):
        """
        fail02.json
        """
        self._run_fail_json("fail02.json", orjson.JSONDecodeError)  # EOF

    def test_fail03(self):
        """
        fail03.json
        """
        self._run_fail_json("fail03.json")

    def test_fail04(self):
        """
        fail04.json
        """
        self._run_fail_json("fail04.json")

    def test_fail05(self):
        """
        fail05.json
        """
        self._run_fail_json("fail05.json")

    def test_fail06(self):
        """
        fail06.json
        """
        self._run_fail_json("fail06.json")

    def test_fail07(self):
        """
        fail07.json
        """
        self._run_fail_json("fail07.json")

    def test_fail08(self):
        """
        fail08.json
        """
        self._run_fail_json("fail08.json")

    def test_fail09(self):
        """
        fail09.json
        """
        self._run_fail_json("fail09.json")

    def test_fail10(self):
        """
        fail10.json
        """
        self._run_fail_json("fail10.json")

    def test_fail11(self):
        """
        fail11.json
        """
        self._run_fail_json("fail11.json")

    def test_fail12(self):
        """
        fail12.json
        """
        self._run_fail_json("fail12.json")

    def test_fail13(self):
        """
        fail13.json
        """
        self._run_fail_json("fail13.json")

    def test_fail14(self):
        """
        fail14.json
        """
        self._run_fail_json("fail14.json")

    def test_fail15(self):
        """
        fail15.json
        """
        self._run_fail_json("fail15.json")

    def test_fail16(self):
        """
        fail16.json
        """
        self._run_fail_json("fail16.json")

    def test_fail17(self):
        """
        fail17.json
        """
        self._run_fail_json("fail17.json")

    def test_fail18(self):
        """
        fail18.json
        """
        self._run_pass_json(
            "fail18.json",
            b'[[[[[[[[[[[[[[[[[[[["Too deep"]]]]]]]]]]]]]]]]]]]]',
        )

    def test_fail19(self):
        """
        fail19.json
        """
        self._run_fail_json("fail19.json")

    def test_fail20(self):
        """
        fail20.json
        """
        self._run_fail_json("fail20.json")

    def test_fail21(self):
        """
        fail21.json
        """
        self._run_fail_json("fail21.json")

    def test_fail22(self):
        """
        fail22.json
        """
        self._run_fail_json("fail22.json")

    def test_fail23(self):
        """
        fail23.json
        """
        self._run_fail_json("fail23.json")

    def test_fail24(self):
        """
        fail24.json
        """
        self._run_fail_json("fail24.json")

    def test_fail25(self):
        """
        fail25.json
        """
        self._run_fail_json("fail25.json")

    def test_fail26(self):
        """
        fail26.json
        """
        self._run_fail_json("fail26.json")

    def test_fail27(self):
        """
        fail27.json
        """
        self._run_fail_json("fail27.json")

    def test_fail28(self):
        """
        fail28.json
        """
        self._run_fail_json("fail28.json")

    def test_fail29(self):
        """
        fail29.json
        """
        self._run_fail_json("fail29.json")

    def test_fail30(self):
        """
        fail30.json
        """
        self._run_fail_json("fail30.json")

    def test_fail31(self):
        """
        fail31.json
        """
        self._run_fail_json("fail31.json")

    def test_fail32(self):
        """
        fail32.json
        """
        self._run_fail_json("fail32.json", orjson.JSONDecodeError)  # EOF

    def test_fail33(self):
        """
        fail33.json
        """
        self._run_fail_json("fail33.json")

    def test_pass01(self):
        """
        pass01.json
        """
        self._run_pass_json("pass01.json", PATTERN_1)

    def test_pass02(self):
        """
        pass02.json
        """
        self._run_pass_json(
            "pass02.json",
            b'[[[[[[[[[[[[[[[[[[["Not too deep"]]]]]]]]]]]]]]]]]]]',
        )

    def test_pass03(self):
        """
        pass03.json
        """
        self._run_pass_json(
            "pass03.json",
            b'{"JSON Test Pattern pass3":{"The outermost value":"must be '
            b'an object or array.","In this test":"It is an object."}}',
        )
