import wandb
from wandb import data_types
import numpy as np
import pytest
import os
import sys

_PY3 = sys.version_info.major == 3 and sys.version_info.minor >= 6
if _PY3:
    from wandb.sdk.interface.dtypes import *
else:
    from wandb.sdk_py27.interface.dtypes import *

class_labels = {1: "tree", 2: "car", 3: "road"}
test_folder = os.path.dirname(os.path.realpath(__file__))
im_path = os.path.join(test_folder, "..", "assets", "test.png")


def test_none_type():
    wb_type = TypeRegistry.type_of(None)
    assert wb_type == NoneType
    wb_type_2 = wb_type.assign(None)
    assert wb_type == wb_type_2
    assert wb_type.assign(1) == NeverType


def test_text_type():
    wb_type = TypeRegistry.type_of("hello")
    assert wb_type == TextType
    wb_type_2 = wb_type.assign("world")
    assert wb_type == wb_type_2
    assert wb_type.assign(1) == NeverType
    assert wb_type.assign(None) == NeverType


def test_number_type():
    wb_type = TypeRegistry.type_of(1.3)
    assert wb_type == NumberType
    wb_type_2 = wb_type.assign(-2)
    assert wb_type == wb_type_2
    assert wb_type.assign("a") == NeverType
    assert wb_type.assign(None) == NeverType


def test_boolean_type():
    wb_type = TypeRegistry.type_of(True)
    assert wb_type == BooleanType
    wb_type_2 = wb_type.assign(False)
    assert wb_type == wb_type_2
    assert wb_type.assign(1) == NeverType
    assert wb_type.assign(None) == NeverType


def test_any_type():
    wb_type = AnyType
    assert wb_type == wb_type.assign(1)
    assert wb_type.assign(None) == NeverType


def test_never_type():
    wb_type = NeverType
    assert wb_type == wb_type.assign(1)
    assert wb_type == wb_type.assign("a")
    assert wb_type == wb_type.assign(True)
    assert wb_type == wb_type.assign(None)

    wb_type = OptionalType(NeverType)
    assert NeverType == wb_type.assign(1)
    assert NeverType == wb_type.assign("a")
    assert NeverType == wb_type.assign(True)
    assert wb_type == wb_type.assign(None)


def test_unknown_type():
    wb_type = UnknownType
    assert wb_type.assign(1) == NumberType
    wb_type_2 = wb_type.assign(None)
    # assert wb_type_2 == OptionalType(UnknownType)
    # assert wb_type_2.assign(None) == wb_type_2
    # exp_type = OptionalType(NumberType)
    # assert wb_type_2.assign(1) == exp_type
    # assert wb_type_2.assign(None) == wb_type_2
    assert wb_type_2 == NeverType
    wb_type_2 = OptionalType(UnknownType)
    assert wb_type_2.assign(1) == OptionalType(NumberType)
    assert wb_type_2.assign(None) == OptionalType(UnknownType)


def test_union_type():
    wb_type = UnionType([NumberType, TextType])
    assert wb_type.assign(1) == wb_type
    assert wb_type.assign("s") == wb_type
    assert wb_type.assign(True) == NeverType

    wb_type = UnionType([NumberType, AnyType])
    assert wb_type.assign(1) == wb_type
    assert wb_type.assign("s") == wb_type
    assert wb_type.assign(True) == wb_type

    wb_type = UnionType([NumberType, UnknownType])
    assert wb_type.assign(1) == wb_type
    assert wb_type.assign("s") == UnionType([NumberType, TextType])
    assert wb_type.assign(None) == NeverType

    wb_type = UnionType([NumberType, OptionalType(UnknownType)])
    assert wb_type.assign(None).assign(True) == UnionType(
        [NumberType, OptionalType(BooleanType)]
    )

    wb_type = UnionType([NumberType, UnionType([TextType, UnknownType])])
    assert wb_type.assign(1) == wb_type
    assert wb_type.assign("s") == wb_type
    assert wb_type.assign(True) == UnionType([NumberType, TextType, BooleanType])
    # assert wb_type.assign(None) == UnionType(
    #     [NumberType, TextType, OptionalType(UnknownType)]
    # )
    assert wb_type.assign(None) == NeverType


def test_const_type():
    wb_type = ConstType(1)
    assert wb_type.assign(1) == wb_type
    assert wb_type.assign("a") == NeverType
    assert wb_type.assign(2) == NeverType


def test_set_const_type():
    wb_type = ConstType(set())
    assert wb_type.assign(set()) == wb_type
    assert wb_type.assign(None) == NeverType
    assert wb_type.assign(set([1])) == NeverType
    assert wb_type.assign([]) == NeverType

    wb_type = ConstType(set([1, 2, 3]))
    assert wb_type.assign(set()) == NeverType
    assert wb_type.assign(None) == NeverType
    assert wb_type.assign(set([1, 2, 3])) == wb_type
    assert wb_type.assign([1, 2, 3]) == NeverType


def test_object_type():
    wb_type = TypeRegistry.type_of(np.random.rand(30))
    assert wb_type.assign(np.random.rand(30)) == wb_type
    assert wb_type.assign(4) == NeverType


def test_list_type():
    assert ListType(dtype=NumberType).assign([]) == ListType(dtype=NumberType)
    assert ListType(dtype=NumberType).assign([1, 2, 3]) == ListType(dtype=NumberType)
    assert ListType(dtype=NumberType).assign([1, "a", 3]) == NeverType


def test_dict_type():
    spec = {"number": NumberType, "nested": {"list_str": ListType(dtype=TextType),}}
    exact = {"number": 1, "nested": {"list_str": ["hello", "world"],}}
    subset = {"nested": {"list_str": ["hi"]}}
    narrow = {"number": 1, "string": "hi"}

    wb_type = TypeRegistry.type_of(exact)
    assert wb_type.assign(exact) == wb_type
    assert wb_type.assign(subset) == NeverType
    assert wb_type.assign(narrow) == NeverType

    wb_type = DictType(dtype=spec, key_policy=KeyPolicy.SUBSET)
    # import pdb; pdb.set_trace()
    assert wb_type.assign(exact) == wb_type
    assert wb_type.assign(subset) == wb_type
    assert wb_type.assign(narrow) == NeverType

    wb_type = DictType(dtype=spec, key_policy=KeyPolicy.UNRESTRICTED)
    combined = {
        "number": NumberType,
        "string": TextType,
        "nested": {"list_str": ListType(dtype=TextType),},
    }
    exp_type = DictType(dtype=combined, key_policy=KeyPolicy.UNRESTRICTED)
    assert wb_type.assign(exact) == wb_type
    assert wb_type.assign(subset) == wb_type
    assert wb_type.assign(narrow) == exp_type

    spec = {
        "optional_number": OptionalType(NumberType),
        "optional_unknown": OptionalType(UnknownType),
    }
    wb_type = DictType(dtype=spec, key_policy=KeyPolicy.EXACT)
    assert wb_type.assign({}) == wb_type
    assert wb_type.assign({"optional_number": 1}) == wb_type
    assert wb_type.assign({"optional_number": "1"}) == NeverType
    assert wb_type.assign({"optional_unknown": "hi"}) == DictType(
        dtype={
            "optional_number": OptionalType(NumberType),
            "optional_unknown": OptionalType(TextType),
        },
        key_policy=KeyPolicy.EXACT,
    )
    assert wb_type.assign({"optional_unknown": None}) == DictType(
        dtype={
            "optional_number": OptionalType(NumberType),
            "optional_unknown": OptionalType(UnknownType),
        },
        key_policy=KeyPolicy.EXACT,
    )

    wb_type = DictType(dtype={"unknown": UnknownType}, key_policy=KeyPolicy.EXACT)
    assert wb_type.assign({}) == NeverType
    assert wb_type.assign({"unknown": None}) == NeverType
    assert wb_type.assign({"unknown": 1}) == DictType(
        dtype={"unknown": NumberType}, key_policy=KeyPolicy.EXACT
    )


def test_nested_dict():
    notation_type = DictType(
        dtype={
            "a": NumberType,
            "b": BooleanType,
            "c": TextType,
            "d": UnknownType,
            "e": {},
            "f": [],
            "g": [
                [
                    {
                        "a": NumberType,
                        "b": BooleanType,
                        "c": TextType,
                        "d": UnknownType,
                        "e": {},
                        "f": [],
                        "g": [[]],
                    }
                ]
            ],
        }
    )
    expanded_type = DictType(
        dtype={
            "a": NumberType,
            "b": BooleanType,
            "c": TextType,
            "d": UnknownType,
            "e": DictType({}),
            "f": ListType(),
            "g": ListType(
                dtype=ListType(
                    dtype=DictType(
                        dtype={
                            "a": NumberType,
                            "b": BooleanType,
                            "c": TextType,
                            "d": UnknownType,
                            "e": DictType({}),
                            "f": ListType(),
                            "g": ListType(dtype=ListType()),
                        }
                    )
                )
            ),
        }
    )

    example = {
        "a": 1,
        "b": True,
        "c": "TextType",
        "d": "hi",
        "e": {},
        "f": [1],
        "g": [
            [
                {
                    "a": 2,
                    "b": False,
                    "c": "TextType",
                    "d": 3,
                    "e": {},
                    "f": [],
                    "g": [[5]],
                }
            ]
        ],
    }
    real_type = DictType(example)

    assert notation_type == expanded_type
    assert notation_type.assign(example) == real_type

    notation_type = DictType(
        dtype={
            "a": NumberType,
            "b": BooleanType,
            "c": TextType,
            "d": UnknownType,
            "e": {},
            "f": [],
            "g": [
                [
                    {
                        "a": NumberType,
                        "b": BooleanType,
                        "c": TextType,
                        "d": UnknownType,
                        "e": {},
                        "f": [],
                        "g": [[]],
                    }
                ]
            ],
        },
        key_policy=KeyPolicy.SUBSET,
    )

    expanded_type = DictType(
        dtype={
            "a": NumberType,
            "b": BooleanType,
            "c": TextType,
            "d": UnknownType,
            "e": DictType({}, key_policy=KeyPolicy.SUBSET),
            "f": ListType(),
            "g": ListType(
                dtype=ListType(
                    dtype=DictType(
                        dtype={
                            "a": NumberType,
                            "b": BooleanType,
                            "c": TextType,
                            "d": UnknownType,
                            "e": DictType({}, key_policy=KeyPolicy.SUBSET),
                            "f": ListType(),
                            "g": ListType(dtype=ListType()),
                        },
                        key_policy=KeyPolicy.SUBSET,
                    )
                )
            ),
        },
        key_policy=KeyPolicy.SUBSET,
    )

    assert notation_type == expanded_type

    wb_type = DictType(
        dtype={
            "l1": {
                "l2": [{"a": NumberType, "b": ListType(), "c": UnknownType,}],
                "l2a": NumberType,
            }
        },
        key_policy=KeyPolicy.SUBSET,
    )
    assert wb_type.assign({}) == wb_type
    assert wb_type.assign(
        {"l1": {"l2": [{"a": 1, "b": [True], "c": "hi"}]}}
    ) == DictType(
        dtype={
            "l1": {
                "l2": [
                    {"a": NumberType, "b": ListType(dtype=BooleanType), "c": TextType,}
                ],
                "l2a": NumberType,
            }
        },
        key_policy=KeyPolicy.SUBSET,
    )

    wb_type = DictType(
        dtype={
            "l1": {
                "l2": [{"a": NumberType, "b": ListType(), "c": UnknownType,}],
                "l2a": NumberType,
            }
        },
        key_policy=KeyPolicy.SUBSET,
    )
    assert wb_type.assign({"l1": {"l2": [{"b": []}]}}) == wb_type
    assert wb_type.assign({"l1": {"l2": [{"b": [1], "c": "hi"}]}}) == DictType(
        dtype={
            "l1": {
                "l2": [
                    {"a": NumberType, "b": ListType(dtype=NumberType), "c": TextType,}
                ],
                "l2a": NumberType,
            }
        },
        key_policy=KeyPolicy.SUBSET,
    )
    assert wb_type.assign({"l1": {"l2": [{"a": "a",}]}}) == NeverType


def test_image_type():
    wb_type = data_types._ImageType()
    image_simple = data_types.Image(np.random.rand(10, 10))
    wb_type_simple = data_types._ImageType(image_simple)
    image_annotated = data_types.Image(
        np.random.rand(10, 10),
        boxes={
            "box_predictions": {
                "box_data": [
                    {
                        "position": {
                            "minX": 0.1,
                            "maxX": 0.2,
                            "minY": 0.3,
                            "maxY": 0.4,
                        },
                        "class_id": 1,
                        "box_caption": "minMax(pixel)",
                        "scores": {"acc": 0.1, "loss": 1.2},
                    },
                ],
                "class_labels": class_labels,
            },
            "box_ground_truth": {
                "box_data": [
                    {
                        "position": {
                            "minX": 0.1,
                            "maxX": 0.2,
                            "minY": 0.3,
                            "maxY": 0.4,
                        },
                        "class_id": 1,
                        "box_caption": "minMax(pixel)",
                        "scores": {"acc": 0.1, "loss": 1.2},
                    },
                ],
                "class_labels": class_labels,
            },
        },
        masks={
            "mask_predictions": {
                "mask_data": np.random.randint(0, 4, size=(30, 30)),
                "class_labels": class_labels,
            },
            "mask_ground_truth": {"path": im_path, "class_labels": class_labels},
        },
    )
    wb_type_annotated = data_types._ImageType(image_annotated)

    image_annotated_differently = data_types.Image(
        np.random.rand(10, 10),
        boxes={
            "box_predictions": {
                "box_data": [
                    {
                        "position": {
                            "minX": 0.1,
                            "maxX": 0.2,
                            "minY": 0.3,
                            "maxY": 0.4,
                        },
                        "class_id": 1,
                        "box_caption": "minMax(pixel)",
                        "scores": {"acc": 0.1, "loss": 1.2},
                    },
                ],
                "class_labels": class_labels,
            },
        },
        masks={
            "mask_predictions": {
                "mask_data": np.random.randint(0, 4, size=(30, 30)),
                "class_labels": class_labels,
            },
            "mask_ground_truth_2": {"path": im_path, "class_labels": class_labels},
        },
    )

    assert wb_type.assign(image_simple) == wb_type_simple
    assert wb_type.assign(image_annotated) == wb_type_annotated
    assert wb_type_annotated.assign(image_simple) == NeverType
    assert wb_type_annotated.assign(image_annotated_differently) == NeverType


def test_classes_type():
    wb_classes = data_types.Classes(
        [
            {"id": 1, "name": "cat"},
            {"id": 2, "name": "dog"},
            {"id": 3, "name": "horse"},
        ]
    )

    wb_class_type = data_types._ClassesMemberType(wb_classes)

    assert wb_class_type.assign(1) == wb_class_type
    assert wb_class_type.assign(0) == NeverType


def test_table_type():
    table_1 = wandb.Table(columns=["col"], data=[[1]])
    t1 = data_types._TableType(table_1)
    table_2 = wandb.Table(columns=["col"], data=[[1.3]])
    table_3 = wandb.Table(columns=["col"], data=[["a"]])
    assert t1.assign(table_2) == t1
    assert t1.assign(table_3) == NeverType


def test_table_implicit_types():
    table = wandb.Table(columns=["col"])
    table.add_data(None)
    table.add_data(1)
    with pytest.raises(TypeError):
        table.add_data("a")

    table = wandb.Table(columns=["col"], optional=False)
    with pytest.raises(TypeError):
        table.add_data(None)
    table.add_data(1)
    with pytest.raises(TypeError):
        table.add_data("a")


def test_table_explicit_types():
    table = wandb.Table(columns=["col"], dtype=NumberType)
    table.add_data(None)
    table.add_data(1)
    with pytest.raises(TypeError):
        table.add_data("a")

    table = wandb.Table(columns=["col"], optional=False, dtype=NumberType)
    with pytest.raises(TypeError):
        table.add_data(None)
    table.add_data(1)
    with pytest.raises(TypeError):
        table.add_data("a")


def test_table_type_cast():

    table = wandb.Table(columns=["type_col"])
    table.add_data(1)

    wb_classes = data_types.Classes(
        [
            {"id": 1, "name": "cat"},
            {"id": 2, "name": "dog"},
            {"id": 3, "name": "horse"},
        ]
    )

    table.cast("type_col", wb_classes)
    table.add_data(2)

    with pytest.raises(TypeError):
        table.add_data(4)
