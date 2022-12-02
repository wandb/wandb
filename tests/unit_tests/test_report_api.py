from typing import Optional, Union

import pytest
from wandb.apis.reports.util import Attr, Base
from wandb.apis.reports.validators import Between, OneOf, TypeValidator


@pytest.mark.usefixtures("user")
class WandbObject(Base):
    untyped = Attr(json_path="spec.untyped")
    typed: Optional[str] = Attr(json_path="spec.typed")
    nested_path: Optional[str] = Attr(
        json_path="spec.deeply.nested.example",
    )
    two_paths: list = Attr(
        json_path=["spec.two1", "spec.two2"],
        validators=[TypeValidator(Union[int, float, None], how="keys")],
    )
    two_nested_paths: list = Attr(
        json_path=["spec.nested.first", "spec.nested.second"],
        validators=[TypeValidator(Optional[str], how="keys")],
    )
    validated_scalar: int = Attr(
        json_path="spec.validated_scalar", validators=[Between(0, 3)]
    )
    validated_list: list = Attr(
        json_path="spec.validated_list", validators=[Between(0, 3, how="keys")]
    )
    validated_dict: dict = Attr(
        json_path="spec.validated_dict",
        validators=[OneOf(["a", "b"], how="keys"), Between(0, 3, how="values")],
    )
    objects_with_spec: list = Attr(
        json_path="spec.objects_with_spec",
        # validators=[TypeValidator("WandbObject", how="keys")],
    )

    def __init__(self):
        super().__init__()
        self.untyped = None
        self.typed = None
        self.nested_path = None
        self.two_paths = [None, None]
        self.two_nested_paths = [None, None]
        self.validated_scalar = 0
        self.validated_list = []
        self.validated_dict = {}
        self.objects_with_spec = []


# Self-referential -- must add post-hoc
WandbObject.objects_with_spec.validators = [TypeValidator(WandbObject, how="keys")]


@pytest.mark.usefixtures("user")
class TestAttrSystem:
    def test_untyped(self):
        o = WandbObject()
        o.untyped = "untyped_value"
        assert o.spec["untyped"] == "untyped_value"
        assert o.untyped == "untyped_value"

    def test_typed(self):
        o = WandbObject()
        o.typed = "typed_value"
        assert o.spec["typed"] == "typed_value"
        with pytest.raises(TypeError):
            o.typed = 1
        assert o.spec["typed"] == "typed_value"
        assert o.typed == "typed_value"

    def test_two_paths(self):
        o = WandbObject()
        o.two_paths = [1, 2]
        assert "two_paths" not in o.spec
        assert o.spec["two1"] == 1
        assert o.spec["two2"] == 2
        assert o.two_paths == [1, 2]

    def test_nested_path(self):
        o = WandbObject()
        o.nested_path = "nested_value"
        assert o.spec["deeply"]["nested"]["example"] == "nested_value"
        assert o.nested_path == "nested_value"

    def test_two_nested_paths(self):
        o = WandbObject()
        o.two_nested_paths = ["first", "second"]
        assert "two_nested_paths" not in o.spec
        assert o.spec["nested"]["first"] == "first"
        assert o.spec["nested"]["second"] == "second"
        assert o.two_nested_paths == ["first", "second"]

    def test_validated_scalar(self):
        o = WandbObject()
        o.validated_scalar = 1
        assert o.spec["validated_scalar"] == 1

        with pytest.raises(ValueError):
            o.validated_scalar = -999
        assert o.spec["validated_scalar"] == 1
        assert o.validated_scalar == 1

    def test_validated_list(self):
        o = WandbObject()
        o.validated_list = [1, 2, 3]
        assert o.spec["validated_list"] == [1, 2, 3]

        with pytest.raises(ValueError):
            o.validated_list = [-1, -2, -3]
        assert o.spec["validated_list"] == [1, 2, 3]

        with pytest.raises(ValueError):
            o.validated_list = [1, 2, -999]
        assert o.spec["validated_list"] == [1, 2, 3]
        assert o.validated_list == [1, 2, 3]

    def test_validated_dict_keys(self):
        o = WandbObject()
        o.validated_dict = {"a": 1, "b": 2}
        assert o.spec["validated_dict"] == {"a": 1, "b": 2}

        with pytest.raises(ValueError):
            o.validated_dict = {"a": 1, "invalid_key": 2}
        assert o.spec["validated_dict"] == {"a": 1, "b": 2}
        assert o.validated_dict == {"a": 1, "b": 2}

    def test_validated_dict_values(self):
        o = WandbObject()
        o.validated_dict = {"a": 1, "b": 2}
        assert o.spec["validated_dict"] == {"a": 1, "b": 2}

        with pytest.raises(ValueError):
            o.validated_dict = {"a": 1, "b": -999}
        assert o.spec["validated_dict"] == {"a": 1, "b": 2}
        assert o.validated_dict == {"a": 1, "b": 2}

    def test_nested_objects_with_spec(self):
        o1 = WandbObject()
        o2 = WandbObject()
        o3 = WandbObject()
        o2.objects_with_spec = [o3]
        o1.objects_with_spec = [o2]

        o3.untyped = "a"
        assert o3.untyped == "a"
        assert o2.objects_with_spec[0].untyped == "a"
        assert o1.objects_with_spec[0].objects_with_spec[0].untyped == "a"

        o2.untyped = "b"
        assert o2.untyped == "b"
        assert o1.objects_with_spec[0].untyped == "b"
