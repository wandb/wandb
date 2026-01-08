# SPDX-License-Identifier: (Apache-2.0 OR MIT)
# Copyright ijl (2018-2025)

import orjson

from .util import needs_data, read_fixture_str


@needs_data
class TestJsonChecker:
    def _run_roundtrip_json(self, filename):
        data = read_fixture_str(filename, "roundtrip")
        assert orjson.dumps(orjson.loads(data)) == data.encode("utf-8")

    def test_roundtrip001(self):
        """
        roundtrip001.json
        """
        self._run_roundtrip_json("roundtrip01.json")

    def test_roundtrip002(self):
        """
        roundtrip002.json
        """
        self._run_roundtrip_json("roundtrip02.json")

    def test_roundtrip003(self):
        """
        roundtrip003.json
        """
        self._run_roundtrip_json("roundtrip03.json")

    def test_roundtrip004(self):
        """
        roundtrip004.json
        """
        self._run_roundtrip_json("roundtrip04.json")

    def test_roundtrip005(self):
        """
        roundtrip005.json
        """
        self._run_roundtrip_json("roundtrip05.json")

    def test_roundtrip006(self):
        """
        roundtrip006.json
        """
        self._run_roundtrip_json("roundtrip06.json")

    def test_roundtrip007(self):
        """
        roundtrip007.json
        """
        self._run_roundtrip_json("roundtrip07.json")

    def test_roundtrip008(self):
        """
        roundtrip008.json
        """
        self._run_roundtrip_json("roundtrip08.json")

    def test_roundtrip009(self):
        """
        roundtrip009.json
        """
        self._run_roundtrip_json("roundtrip09.json")

    def test_roundtrip010(self):
        """
        roundtrip010.json
        """
        self._run_roundtrip_json("roundtrip10.json")

    def test_roundtrip011(self):
        """
        roundtrip011.json
        """
        self._run_roundtrip_json("roundtrip11.json")

    def test_roundtrip012(self):
        """
        roundtrip012.json
        """
        self._run_roundtrip_json("roundtrip12.json")

    def test_roundtrip013(self):
        """
        roundtrip013.json
        """
        self._run_roundtrip_json("roundtrip13.json")

    def test_roundtrip014(self):
        """
        roundtrip014.json
        """
        self._run_roundtrip_json("roundtrip14.json")

    def test_roundtrip015(self):
        """
        roundtrip015.json
        """
        self._run_roundtrip_json("roundtrip15.json")

    def test_roundtrip016(self):
        """
        roundtrip016.json
        """
        self._run_roundtrip_json("roundtrip16.json")

    def test_roundtrip017(self):
        """
        roundtrip017.json
        """
        self._run_roundtrip_json("roundtrip17.json")

    def test_roundtrip018(self):
        """
        roundtrip018.json
        """
        self._run_roundtrip_json("roundtrip18.json")

    def test_roundtrip019(self):
        """
        roundtrip019.json
        """
        self._run_roundtrip_json("roundtrip19.json")

    def test_roundtrip020(self):
        """
        roundtrip020.json
        """
        self._run_roundtrip_json("roundtrip20.json")

    def test_roundtrip021(self):
        """
        roundtrip021.json
        """
        self._run_roundtrip_json("roundtrip21.json")

    def test_roundtrip022(self):
        """
        roundtrip022.json
        """
        self._run_roundtrip_json("roundtrip22.json")

    def test_roundtrip023(self):
        """
        roundtrip023.json
        """
        self._run_roundtrip_json("roundtrip23.json")

    def test_roundtrip024(self):
        """
        roundtrip024.json
        """
        self._run_roundtrip_json("roundtrip24.json")

    def test_roundtrip025(self):
        """
        roundtrip025.json
        """
        self._run_roundtrip_json("roundtrip25.json")

    def test_roundtrip026(self):
        """
        roundtrip026.json
        """
        self._run_roundtrip_json("roundtrip26.json")

    def test_roundtrip027(self):
        """
        roundtrip027.json
        """
        self._run_roundtrip_json("roundtrip27.json")
