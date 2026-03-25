"""Tests for protobuf version compatibility (issue #11548).

Verifies that wandb's proto wrapper modules correctly dispatch to the
version-specific pb2 files for all supported protobuf major versions,
and that the v7 generated files correctly declare gencode version 7.x.
"""
import importlib
import sys
from pathlib import Path

import google.protobuf
import pytest


def _get_proto_major() -> str:
    return google.protobuf.__version__.split(".")[0]


class TestProtobufVersionDispatch:
    """Ensure wrapper files route to the correct version-specific subpackage."""

    def test_wrapper_uses_major_version_digit(self):
        """Version dispatch uses the major version integer, not the first char."""
        major = google.protobuf.__version__.split(".")[0]
        # Ensure it is a valid integer (not a string-slice of a multi-digit major)
        assert major.isdigit(), f"Expected numeric major, got {major!r}"
        assert int(major) >= 4

    def test_telemetry_imports_class(self):
        """Imports class must be importable from the top-level wrapper."""
        from wandb.proto.wandb_telemetry_pb2 import Imports

        assert Imports is not None

    def test_telemetry_record_imports_class(self):
        from wandb.proto.wandb_telemetry_pb2 import TelemetryRecord

        assert TelemetryRecord is not None

    def test_telemetry_message_creation(self):
        """Can create and serialize an Imports proto message."""
        from wandb.proto.wandb_telemetry_pb2 import Imports, TelemetryRecord

        imports = Imports()
        imports.torch = True
        imports.keras = True

        record = TelemetryRecord()
        record.imports_init.CopyFrom(imports)

        serialized = record.SerializeToString()
        assert len(serialized) > 0

        record2 = TelemetryRecord()
        record2.ParseFromString(serialized)
        assert record2.imports_init.torch is True
        assert record2.imports_init.keras is True

    def test_internal_pb2_imports(self):
        from wandb.proto.wandb_internal_pb2 import Record

        assert Record is not None

    def test_base_pb2_imports(self):
        from wandb.proto import wandb_base_pb2

        assert wandb_base_pb2 is not None

    def test_settings_pb2_imports(self):
        from wandb.proto import wandb_settings_pb2

        assert wandb_settings_pb2 is not None


class TestV7SubpackageStructure:
    """Verify the v7/ subpackage is properly structured."""

    def test_v7_init_exists(self):
        """wandb/proto/v7/__init__.py must exist so v7 is a proper package."""
        proto_dir = Path(__file__).parent.parent.parent / "wandb" / "proto"
        init_file = proto_dir / "v7" / "__init__.py"
        assert init_file.exists(), (
            "wandb/proto/v7/__init__.py is missing; v7 is not a proper package"
        )

    def test_v7_gencode_version_is_seven(self):
        """All v7 pb2 files must declare gencode major version 7."""
        proto_dir = Path(__file__).parent.parent.parent / "wandb" / "proto" / "v7"
        pb2_files = list(proto_dir.glob("*_pb2.py"))
        assert len(pb2_files) > 0, "No pb2 files found in wandb/proto/v7/"

        for pb2_file in pb2_files:
            content = pb2_file.read_text()
            assert "Protobuf Python Version: 7" in content, (
                f"{pb2_file.name}: expected 'Protobuf Python Version: 7.x.x', "
                f"but still has 6.x version header"
            )
            # The ValidateProtobufRuntimeVersion call must use major=7
            assert (
                "_runtime_version.Domain.PUBLIC,\n    7," in content
                or "_runtime_version.Domain.PUBLIC,\n    7," in content.replace("\r\n", "\n")
            ), (
                f"{pb2_file.name}: ValidateProtobufRuntimeVersion must declare "
                f"gencode major version 7, not 6"
            )

    def test_v7_all_pb2_files_present(self):
        """v7/ must have pb2 files for all proto modules."""
        proto_dir = Path(__file__).parent.parent.parent / "wandb" / "proto" / "v7"
        expected = {
            "wandb_api_pb2.py",
            "wandb_base_pb2.py",
            "wandb_internal_pb2.py",
            "wandb_server_pb2.py",
            "wandb_settings_pb2.py",
            "wandb_sync_pb2.py",
            "wandb_telemetry_pb2.py",
        }
        actual = {f.name for f in proto_dir.glob("*_pb2.py")}
        assert expected <= actual, f"Missing pb2 files in v7/: {expected - actual}"


class TestVersionSubdirInit:
    """All version subdirs should be proper Python packages."""

    @pytest.mark.parametrize("ver", ["v4", "v5", "v6", "v7"])
    def test_version_subdir_has_init(self, ver):
        proto_dir = Path(__file__).parent.parent.parent / "wandb" / "proto"
        init_file = proto_dir / ver / "__init__.py"
        assert init_file.exists(), (
            f"wandb/proto/{ver}/__init__.py is missing"
        )
