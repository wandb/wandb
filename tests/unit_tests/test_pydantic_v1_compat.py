"""Basic, minimal tests for the pydantic v1 compatibility layer.

Because Pydantic v1 is already EOL at the time of implementation, these tests
are not intended to be comprehensive, nor is the v1 compatibility layer intended
to be a full backport of pydantic v2.

Whenever possible, users should strongly prefer upgrading to Pydantic v2 to
ensure full compatibility, though this is understandably not always a feasible
option.

Consider removing tests once Pydantic v1 support is dropped.
"""

# Ignored linter rules to ensure compatibility with older pydantic and/or python versions.
# ruff: noqa: UP006  # allow e.g. `List[X]` instead of `list[x]`
# ruff: noqa: UP035  # allow deprecated typing module imports
# ruff: noqa: UP045  # allow e.g. `Optional[X]` instead of `X | None` (pydantic<2.6)

from __future__ import annotations

import json
from typing import Any, List, Optional

from pydantic import ConfigDict, Field, Json, ValidationError
from pytest import raises
from wandb._pydantic import (
    IS_PYDANTIC_V2,
    AliasChoices,
    CompatBaseModel,
    GQLInput,
    GQLResult,
    computed_field,
    field_validator,
    model_validator,
)
from wandb.sdk.artifacts._generated import GetArtifactFiles, TypeInfoFragment


def test_field_validator_before():
    class Model(CompatBaseModel):
        name: str

        @field_validator("name", mode="before")
        @classmethod
        def validate_name(cls, v: Any) -> str:
            return str(v).upper()

    obj = Model(name="test")
    assert obj.name == "TEST"


def test_field_validator_after():
    class Model(CompatBaseModel):
        name: str

        @field_validator("name", mode="after")
        @classmethod
        def validate_name(cls, v: str) -> str:
            return v.lower()

    obj = Model(name="TEST")
    assert obj.name == "test"


def test_model_validator_before():
    class Model(CompatBaseModel):
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
    class Model(CompatBaseModel):
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
    class Model(CompatBaseModel):
        x: int
        y: int

        @computed_field
        def sum(self) -> int:
            return self.x + self.y

    obj = Model(x=1, y=2)
    assert obj.sum == 3


def test_computed_field_property():
    class Model(CompatBaseModel):
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

    class Model(CompatBaseModel):
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
    class Model(CompatBaseModel):
        x: int
        y: str

    assert set(Model.model_fields.keys()) == {"x", "y"}


def test_model_fields_set_property():
    class Model(CompatBaseModel):
        x: int
        y: Optional[str] = (
            None  # `Optional[X]` instead of `X | None` for pydantic<2.6 compatibility
        )

    obj = Model(x=1)
    assert obj.model_fields_set == {"x"}


def test_model_validation_methods():
    class Model(CompatBaseModel):
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
    class Model(CompatBaseModel):
        x: int
        y: str

    obj = Model(x=1, y="test")

    assert obj.model_dump() == {"x": 1, "y": "test"}
    assert json.loads(obj.model_dump_json()) == {"x": 1, "y": "test"}


def test_model_copy():
    class Model(CompatBaseModel):
        x: int
        y: str

    orig = Model(x=1, y="test")
    copy = orig.model_copy()

    assert copy.x == orig.x
    assert copy.y == orig.y
    assert copy is not orig


def test_model_config_conversion():
    class Model(CompatBaseModel):
        model_config = ConfigDict(
            populate_by_name=True,
            str_to_lower=True,
        )

        value: str

    obj = Model(value="TEST")
    assert obj.value == "test"


def test_model_dump_methods_with_json_fields():
    class Model(CompatBaseModel):
        x: int
        req_json_field: Json[List[int]]
        opt_json_field: Optional[Json[List[int]]] = None
        unset_opt_json_field: Optional[Json[List[int]]] = None

    obj = Model(
        x=1,
        req_json_field="[1, 2, 3]",
        opt_json_field="[4, 5, 6]",
    )

    # Check default `.model_dump()` behavior.
    # When `round_trip=False`, Json fields aren't re-serialized.
    assert obj.model_dump() == {
        "x": 1,
        "req_json_field": [1, 2, 3],
        "opt_json_field": [4, 5, 6],
        "unset_opt_json_field": None,
    }

    # Check `.model_dump(round_trip=True)` behavior.
    rt_dict = obj.model_dump(round_trip=True)

    # NOTE: We avoid asserting on exact JSON strings here, since:
    # - pydantic v2 dumps compact JSON by default, e.g. `"[1,2,3]"`
    # - pydantic v1 dumps JSON with whitespace by default, e.g. `"[1, 2, 3]"`
    assert rt_dict["x"] == 1

    assert isinstance(rt_dict["req_json_field"], str)
    assert json.loads(rt_dict["req_json_field"]) == [1, 2, 3]

    assert isinstance(rt_dict["opt_json_field"], str)
    assert json.loads(rt_dict["opt_json_field"]) == [4, 5, 6]

    assert rt_dict["unset_opt_json_field"] is None

    # Check that `.model_dump_json(round_trip=True)` behavior is consistent.
    rt_json = obj.model_dump_json(round_trip=True)
    assert json.loads(rt_json) == obj.model_dump(round_trip=True)


class Item(CompatBaseModel):
    val: int


class ListFields(CompatBaseModel):
    required_list: List[Item] = Field(min_length=1, max_length=3)
    optional_list: Optional[List[Item]] = Field(
        default=None, min_length=1, max_length=3
    )


def test_field_constraints_on_list_fields():
    # Valid values
    valid_model1 = ListFields(required_list=[Item(val=1), Item(val=2), Item(val=3)])
    assert valid_model1.required_list == [Item(val=1), Item(val=2), Item(val=3)]
    assert valid_model1.optional_list is None

    valid_model2 = ListFields(
        required_list=[Item(val=1), Item(val=2), Item(val=3)], optional_list=None
    )
    assert valid_model2.required_list == [Item(val=1), Item(val=2), Item(val=3)]
    assert valid_model2.optional_list is None

    valid_model3 = ListFields(
        required_list=[Item(val=1)], optional_list=[Item(val=123)]
    )
    assert valid_model3.required_list == [Item(val=1)]
    assert valid_model3.optional_list == [Item(val=123)]

    # Invalid values are deliberately NOT tested here.
    #
    # Unfortunately, we cannot support runtime validation of list length
    # constraints in Pydantic v1 due to issues with deferred type annotations
    # via `from __future__ import annotations`.
    #
    # See: https://github.com/pydantic/pydantic/issues/3745
    #
    # We only check that the class DEFINITION (above) does not raise an error
    # when the model builds (e.g. at import time).


def test_field_constraints_on_str_fields():
    class StringFields(CompatBaseModel):
        required_str: str = Field(min_length=1, max_length=3, pattern=r"^[a-z]+$")
        optional_str: Optional[str] = Field(
            default=None, min_length=1, max_length=3, pattern=r"^[a-z]+$"
        )

    # Valid values
    valid_model1 = StringFields(required_str="abc")
    assert valid_model1.required_str == "abc"
    assert valid_model1.optional_str is None

    valid_model2 = StringFields(required_str="abc", optional_str=None)
    assert valid_model2.required_str == "abc"
    assert valid_model2.optional_str is None

    valid_model3 = StringFields(required_str="a", optional_str="def")
    assert valid_model3.required_str == "a"
    assert valid_model3.optional_str == "def"

    # Invalid values
    with raises(ValidationError):
        # required too short
        StringFields(required_str="")
    with raises(ValidationError):
        # required too long
        StringFields(required_str="abcd")
    with raises(ValidationError):
        # required ok; optional too short
        StringFields(required_str="a", optional_str="")
    with raises(ValidationError):
        # required ok; optional too long
        StringFields(required_str="a", optional_str="abcd")
    with raises(ValidationError):
        # required doesn't match pattern; optional ok
        StringFields(required_str="ABC", optional_str="def")
    with raises(ValidationError):
        # required ok; optional doesn't match pattern
        StringFields(required_str="abc", optional_str="DEF")
    with raises(ValidationError):
        # neither matches pattern
        StringFields(required_str="ABC", optional_str="123")


# ------------------------------------------------------------------------------
def test_generated_pydantic_fragment_validates_response_data():
    """Check that the generated fragment validates the response data.

    In Pydantic v1 environments, this partly guards against regressions of:
    - https://github.com/wandb/wandb/pull/9795
    """
    response_data = {
        "project": {
            "artifactType": {
                "artifact": {
                    "files": {
                        "edges": [
                            {
                                "node": {
                                    "id": "QXJ0aWZhY3RGaWxlOjE2OTgzNjI1MDc6cmFuZG9tX2ltYWdlLnBuZw==",
                                    "name": "random_image.png",
                                    "url": "https://api.wandb.fake/artifactsV2/gcp-us/wandb/abcdef",
                                    "sizeBytes": 30168,
                                    "storagePath": "wandb_artifacts/626357751/1698362507/7e8ff39b55a1a62101758a6dc7a69f70",
                                    "mimetype": None,
                                    "updatedAt": None,
                                    "digest": "fo/zm1WhpiEBdYptx6afcA==",
                                    "md5": "fo/zm1WhpiEBdYptx6afcA==",
                                    "directUrl": "https://fake-url.com",
                                },
                                "cursor": "YXJyYXljb25uZWN0aW9uOjA=",
                            }
                        ],
                        "pageInfo": {
                            "endCursor": "YXJyYXljb25uZWN0aW9uOjA=",
                            "hasNextPage": False,
                        },
                    }
                }
            }
        }
    }
    validated = GetArtifactFiles.model_validate(response_data)
    assert (
        validated.project.artifact_type.artifact.files.edges[0].node.name
        == "random_image.png"
    )


def test_type_info_fragment_validates_response_data():
    response_data = {
        "name": "artifact",
        "fields": [
            {
                "name": "files",
                "args": [
                    {"name": "names"},
                    {"name": "after"},
                    {"name": "first"},
                ],
            }
        ],
        "inputFields": [],
    }
    validated = TypeInfoFragment.model_validate(response_data)
    assert validated.name == "artifact"


# ------------------------------------------------------------------------------
class NestedInput(GQLInput):
    inner_str: Optional[str] = None
    inner_int: Optional[int] = None


class CreateThingInput(GQLInput):
    required_value: int
    optional_str: Optional[str] = None
    optional_int: Optional[int] = None
    nested: Optional[NestedInput] = None


NestedInput.model_rebuild()
CreateThingInput.model_rebuild()


def test_gql_input_dump_excludes_none_by_default():
    """Check that GQLInput classes omit None-valued fields by default but allow for overrides."""
    obj = CreateThingInput(
        required_value=1,
        optional_str=None,
        nested={"inner_str": "inside"},
    )

    # By default, None-valued fields are excluded
    expected_with_default = {"required_value": 1, "nested": {"inner_str": "inside"}}
    assert obj.model_dump() == expected_with_default
    assert json.loads(obj.model_dump_json()) == expected_with_default

    # Overrides are respected
    expected_with_nones = {
        "required_value": 1,
        "optional_str": None,
        "optional_int": None,
        "nested": {
            "inner_str": "inside",
            "inner_int": None,
        },
    }
    assert obj.model_dump(exclude_none=False) == expected_with_nones
    assert json.loads(obj.model_dump_json(exclude_none=False)) == expected_with_nones


class ThingResult(GQLResult):
    foo_bar: int
    hello_world: str = Field(alias="helloWORLD")


def test_gql_result_is_frozen_and_uses_camelcase_aliases_by_default():
    """Check that GQLResult classes are frozen and use camelCase aliases by default."""
    result = ThingResult.model_validate({"fooBar": 7, "helloWORLD": "good morning"})

    # camelCase aliasing is applied by default for dumps
    assert result.model_dump() == {"fooBar": 7, "helloWORLD": "good morning"}

    # Instances are frozen/immutable
    expectation = raises(ValidationError if IS_PYDANTIC_V2 else TypeError)
    with expectation:
        result.foo_bar = 9  # type: ignore[misc]
