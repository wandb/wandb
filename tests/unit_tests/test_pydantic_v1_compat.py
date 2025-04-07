"""Basic, minimal tests for the pydantic v1 compatibility layer.

Because Pydantic v1 is already EOL at the time of implementation, these tests
are not intended to be comprehensive, nor is the v1 compatibility layer intended
to be a full backport of pydantic v2.

Whenever possible, users should strongly prefer upgrading to Pydantic v2 to
ensure full compatibility, though this is understandably not always a feasible
option.

Consider removing tests once Pydantic v1 support is dropped.
"""

from __future__ import annotations

import json
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from pytest import raises
from wandb._pydantic.v1_compat import (
    IS_PYDANTIC_V2,
    AliasChoices,
    PydanticCompatMixin,
    computed_field,
    field_validator,
    model_validator,
)


def test_field_validator_before():
    class Model(PydanticCompatMixin, BaseModel):
        name: str

        @field_validator("name", mode="before")
        @classmethod
        def validate_name(cls, v: Any) -> str:
            return str(v).upper()

    obj = Model(name="test")
    assert obj.name == "TEST"


def test_field_validator_after():
    class Model(PydanticCompatMixin, BaseModel):
        name: str

        @field_validator("name", mode="after")
        @classmethod
        def validate_name(cls, v: str) -> str:
            return v.lower()

    obj = Model(name="TEST")
    assert obj.name == "test"


def test_model_validator_before():
    class Model(PydanticCompatMixin, BaseModel):
        x: int
        y: int

        @model_validator(mode="before")
        @classmethod
        def validate_values(cls, values: dict[str, Any]) -> dict[str, Any]:
            values["x"] = values.get("x", 0) + 1
            values["y"] = values.get("y", 0) + 1
            return values

    obj = Model(x=1, y=2)
    assert obj.x == 2
    assert obj.y == 3


def test_model_validator_after():
    class Model(PydanticCompatMixin, BaseModel):
        x: int
        y: int

        @model_validator(mode="after")
        def validate_values(self) -> dict[str, Any]:
            self.x = self.x + 1
            self.y = self.y + 1
            return self

    obj = Model(x=1, y=2)
    assert obj.x == 2
    assert obj.y == 3


def test_computed_field_method():
    class Model(PydanticCompatMixin, BaseModel):
        x: int
        y: int

        @computed_field
        def sum(self) -> int:
            return self.x + self.y

    obj = Model(x=1, y=2)
    assert obj.sum == 3


def test_computed_field_property():
    class Model(PydanticCompatMixin, BaseModel):
        x: int
        y: int

        @computed_field
        @property
        def sum(self) -> int:
            return self.x + self.y

    obj = Model(x=1, y=2)
    assert obj.sum == 3


def test_alias_choices():
    from contextlib import nullcontext as does_not_raise

    class Model(PydanticCompatMixin, BaseModel):
        value: str = Field(validation_alias=AliasChoices("val", "v"))

    # NOTE: Pydantic v1 compatibility isn't currently implemented for AliasChoices.
    # For now we just ensure it won't raise an error on class definition.

    expectation = does_not_raise() if IS_PYDANTIC_V2 else raises(ValidationError)

    # Test first alias
    with expectation:
        obj1 = Model.model_validate({"val": "test"})
        assert obj1.value == "test"

    # Test second alias
    with expectation:
        obj2 = Model.model_validate({"v": "test"})
        assert obj2.value == "test"


def test_model_fields_class_property():
    class Model(PydanticCompatMixin, BaseModel):
        x: int
        y: str

    assert set(Model.model_fields.keys()) == {"x", "y"}


def test_model_fields_set_property():
    class Model(PydanticCompatMixin, BaseModel):
        x: int
        y: Optional[str] = None  # noqa: UP007  # `Optional[X]` instead of `X | None` for pydantic<2.6 compatibility

    obj = Model(x=1)
    assert obj.model_fields_set == {"x"}


def test_model_validation_methods():
    class Model(PydanticCompatMixin, BaseModel):
        x: int
        y: str

    # Test model_validate
    obj1 = Model.model_validate({"x": 1, "y": "test"})
    assert obj1.x == 1
    assert obj1.y == "test"

    # Test model_validate_json
    obj2 = Model.model_validate_json('{"x": 2, "y": "test2"}')
    assert obj2.x == 2
    assert obj2.y == "test2"


def test_model_dump_methods():
    class Model(PydanticCompatMixin, BaseModel):
        x: int
        y: str

    obj = Model(x=1, y="test")

    assert obj.model_dump() == {"x": 1, "y": "test"}
    assert json.loads(obj.model_dump_json()) == {"x": 1, "y": "test"}


def test_model_copy():
    class Model(PydanticCompatMixin, BaseModel):
        x: int
        y: str

    orig = Model(x=1, y="test")
    copy = orig.model_copy()

    assert copy.x == orig.x
    assert copy.y == orig.y
    assert copy is not orig


def test_model_config_conversion():
    class Model(PydanticCompatMixin, BaseModel):
        model_config = ConfigDict(
            populate_by_name=True,
            str_to_lower=True,
        )

        value: str

    obj = Model(value="TEST")
    assert obj.value == "test"
