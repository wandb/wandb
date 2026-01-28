# SPDX-License-Identifier: (Apache-2.0 OR MIT)
# Copyright ijl (2023-2025)

import random

import pytest

import orjson

try:
    from faker import Faker
except ImportError:
    Faker = None  # type: ignore

NUM_LOOPS = 10
NUM_SHUFFLES = 10
NUM_ENTRIES = 250

FAKER_LOCALES = [
    "ar_AA",
    "fi_FI",
    "fil_PH",
    "he_IL",
    "ja_JP",
    "th_TH",
    "tr_TR",
    "uk_UA",
    "vi_VN",
]


class TestFaker:
    @pytest.mark.skipif(Faker is None, reason="faker not available")
    def test_faker(self):
        fake = Faker(FAKER_LOCALES)
        profile_keys = list(
            set(fake.profile().keys()) - {"birthdate", "current_location"},
        )
        for _ in range(NUM_LOOPS):
            data = [
                {
                    "person": fake.profile(profile_keys),
                    "emoji": fake.emoji(),
                    "text": fake.paragraphs(),
                }
                for _ in range(NUM_ENTRIES)
            ]
            for _ in range(NUM_SHUFFLES):
                random.shuffle(data)
                output = orjson.dumps(data)
                assert orjson.loads(output) == data
