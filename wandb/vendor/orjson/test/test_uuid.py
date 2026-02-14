# SPDX-License-Identifier: (Apache-2.0 OR MIT)
# Copyright ijl (2020-2025), Rami Chowdhury (2020)

import uuid

import pytest

import orjson


class TestUUID:
    def test_uuid_immutable(self):
        """
        UUID objects are immutable
        """
        val = uuid.uuid4()
        with pytest.raises(TypeError):
            val.int = 1  # type: ignore
        with pytest.raises(TypeError):
            val.int = None  # type: ignore

    def test_uuid_int(self):
        """
        UUID.int is a 128-bit integer
        """
        val = uuid.UUID("7202d115-7ff3-4c81-a7c1-2a1f067b1ece")
        assert isinstance(val.int, int)
        assert val.int >= 2**64
        assert val.int < 2**128
        assert val.int == 151546616840194781678008611711208857294

    def test_uuid_overflow(self):
        """
        UUID.int can't trigger errors in _PyLong_AsByteArray
        """
        with pytest.raises(ValueError):
            uuid.UUID(int=2**128)
        with pytest.raises(ValueError):
            uuid.UUID(int=-1)

    def test_uuid_subclass(self):
        """
        UUID subclasses are not serialized
        """

        class AUUID(uuid.UUID):
            pass

        with pytest.raises(orjson.JSONEncodeError):
            orjson.dumps(AUUID("{12345678-1234-5678-1234-567812345678}"))

    def test_serializes_withopt(self):
        """
        dumps() accepts deprecated OPT_SERIALIZE_UUID
        """
        assert (
            orjson.dumps(
                uuid.UUID("7202d115-7ff3-4c81-a7c1-2a1f067b1ece"),
                option=orjson.OPT_SERIALIZE_UUID,
            )
            == b'"7202d115-7ff3-4c81-a7c1-2a1f067b1ece"'
        )

    def test_nil_uuid(self):
        assert (
            orjson.dumps(uuid.UUID("00000000-0000-0000-0000-000000000000"))
            == b'"00000000-0000-0000-0000-000000000000"'
        )

    def test_all_ways_to_create_uuid_behave_equivalently(self):
        # Note that according to the docstring for the uuid.UUID class, all the
        # forms below are equivalent -- they end up with the same value for
        # `self.int`, which is all that really matters
        uuids = [
            uuid.UUID("{12345678-1234-5678-1234-567812345678}"),
            uuid.UUID("12345678123456781234567812345678"),
            uuid.UUID("urn:uuid:12345678-1234-5678-1234-567812345678"),
            uuid.UUID(bytes=b"\x12\x34\x56\x78" * 4),
            uuid.UUID(
                bytes_le=b"\x78\x56\x34\x12\x34\x12\x78\x56\x12\x34\x56\x78\x12\x34\x56\x78",
            ),
            uuid.UUID(fields=(0x12345678, 0x1234, 0x5678, 0x12, 0x34, 0x567812345678)),
            uuid.UUID(int=0x12345678123456781234567812345678),
        ]
        result = orjson.dumps(uuids)
        canonical_uuids = [f'"{u!s}"' for u in uuids]
        serialized = ("[{}]".format(",".join(canonical_uuids))).encode("utf8")
        assert result == serialized

    def test_serializes_correctly_with_leading_zeroes(self):
        instance = uuid.UUID(int=0x00345678123456781234567812345678)
        assert orjson.dumps(instance) == (f'"{instance!s}"').encode("utf-8")

    def test_all_uuid_creation_functions_create_serializable_uuids(self):
        uuids = (
            uuid.uuid1(),
            uuid.uuid3(uuid.NAMESPACE_DNS, "python.org"),
            uuid.uuid4(),
            uuid.uuid5(uuid.NAMESPACE_DNS, "python.org"),
        )
        for val in uuids:
            assert orjson.dumps(val) == f'"{val}"'.encode("utf-8")
