"""Basic tests for W&B's Pydantic helper layer."""

from __future__ import annotations

import json
from typing import Any

from pydantic import ConfigDict, Field, Json, ValidationError
from pytest import raises
from wandb._pydantic import (
    AliasChoices,
    CompatBaseModel,
    GQLInput,
    GQLResult,
    computed_field,
    field_validator,
    model_validator,
)
from wandb.sdk.artifacts._generated import ArtifactMembershipFiles


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
    class Model(CompatBaseModel):
        value: str = Field(validation_alias=AliasChoices("val", "v"))

    obj1 = Model.model_validate({"val": "test"})
    assert obj1.value == "test"

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
        y: str | None = None

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
        req_json_field: Json[list[int]]
        opt_json_field: Json[list[int]] | None = None
        unset_opt_json_field: Json[list[int]] | None = None

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
    required_list: list[Item] = Field(min_length=1, max_length=3)
    optional_list: list[Item] | None = Field(default=None, min_length=1, max_length=3)


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

    with raises(ValidationError):
        ListFields(required_list=[])
    with raises(ValidationError):
        ListFields(required_list=[Item(val=1)], optional_list=[])
    with raises(ValidationError):
        ListFields(required_list=[Item(val=1), Item(val=2), Item(val=3), Item(val=4)])


def test_field_constraints_on_str_fields():
    class StringFields(CompatBaseModel):
        required_str: str = Field(min_length=1, max_length=3, pattern=r"^[a-z]+$")
        optional_str: str | None = Field(
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
    """Check that the generated fragment validates the response data."""
    response_data = {
        "project": {
            "artifactCollection": {
                "__typename": "ArtifactCollection",
                "artifactMembership": {
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
                },
            }
        }
    }
    validated = ArtifactMembershipFiles.model_validate(response_data)
    assert (
        validated.project.artifact_collection.artifact_membership.files.edges[
            0
        ].node.name
        == "random_image.png"
    )


# ------------------------------------------------------------------------------
class NestedInput(GQLInput):
    inner_str: str | None = None
    inner_int: int | None = None


class CreateThingInput(GQLInput):
    required_value: int
    optional_str: str | None = None
    optional_int: int | None = None
    nested: NestedInput | None = None


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
    with raises(ValidationError):
        result.foo_bar = 9  # type: ignore[misc]
