import wandb
from wandb import data_types
import numpy as np
import pytest
import os
import sys

_PY3 = sys.version_info.major == 3 and sys.version_info.minor >= 6
if _PY3:
    from wandb.sdk.interface._dtypes import *
else:
    from wandb.sdk_py27.interface._dtypes import *

class_labels = {1: "tree", 2: "car", 3: "road"}
test_folder = os.path.dirname(os.path.realpath(__file__))
im_path = os.path.join(test_folder, "..", "assets", "test.png")


def test_none_type():
    assert TypeRegistry.type_of(None) == NoneType()
    assert TypeRegistry.type_of(None).assign(None) == NoneType()
    assert TypeRegistry.type_of(None).assign(1) == InvalidType()


def test_string_type():
    assert TypeRegistry.type_of("Hello") == StringType()
    assert TypeRegistry.type_of("Hello").assign("World") == StringType()
    assert TypeRegistry.type_of("Hello").assign(None) == InvalidType()
    assert TypeRegistry.type_of("Hello").assign(1) == InvalidType()


def test_number_type():
    assert TypeRegistry.type_of(1.2) == NumberType()
    assert TypeRegistry.type_of(1.2).assign(1) == NumberType()
    assert TypeRegistry.type_of(1.2).assign(None) == InvalidType()
    assert TypeRegistry.type_of(1.2).assign("hi") == InvalidType()


def test_boolean_type():
    assert TypeRegistry.type_of(True) == BooleanType()
    assert TypeRegistry.type_of(True).assign(False) == BooleanType()
    assert TypeRegistry.type_of(True).assign(None) == InvalidType()
    assert TypeRegistry.type_of(True).assign(1) == InvalidType()


def test_any_type():
    assert AnyType() == AnyType().assign(1)
    assert AnyType().assign(None) == InvalidType()


def test_never_type():
    assert InvalidType().assign(1) == InvalidType()
    assert InvalidType().assign("a") == InvalidType()
    assert InvalidType().assign(True) == InvalidType()
    assert InvalidType().assign(None) == InvalidType()


def test_unknown_type():
    assert UnknownType().assign(1) == NumberType()
    assert UnknownType().assign(None) == InvalidType()


def test_union_type():
    wb_type = UnionType([float, str])
    assert wb_type.assign(1) == wb_type
    assert wb_type.assign("s") == wb_type
    assert wb_type.assign(True) == InvalidType()

    wb_type = UnionType([float, AnyType()])
    assert wb_type.assign(1) == wb_type
    assert wb_type.assign("s") == wb_type
    assert wb_type.assign(True) == wb_type

    wb_type = UnionType([float, UnknownType()])
    assert wb_type.assign(1) == wb_type
    assert wb_type.assign("s") == UnionType([float, StringType()])
    assert wb_type.assign(None) == InvalidType()

    wb_type = UnionType([float, OptionalType(UnknownType())])
    assert wb_type.assign(None).assign(True) == UnionType(
        [float, OptionalType(BooleanType())]
    )

    wb_type = UnionType([float, UnionType([str, UnknownType()])])
    assert wb_type.assign(1) == wb_type
    assert wb_type.assign("s") == wb_type
    assert wb_type.assign(True) == UnionType([float, str, bool])
    assert wb_type.assign(None) == InvalidType()


def test_const_type():
    wb_type = ConstType(1)
    assert wb_type.assign(1) == wb_type
    assert wb_type.assign("a") == InvalidType()
    assert wb_type.assign(2) == InvalidType()


def test_set_const_type():
    wb_type = ConstType(set())
    assert wb_type.assign(set()) == wb_type
    assert wb_type.assign(None) == InvalidType()
    assert wb_type.assign(set([1])) == InvalidType()
    assert wb_type.assign([]) == InvalidType()

    wb_type = ConstType(set([1, 2, 3]))
    assert wb_type.assign(set()) == InvalidType()
    assert wb_type.assign(None) == InvalidType()
    assert wb_type.assign(set([1, 2, 3])) == wb_type
    assert wb_type.assign([1, 2, 3]) == InvalidType()


def test_object_type():
    wb_type = TypeRegistry.type_of(np.random.rand(30))
    assert wb_type.assign(np.random.rand(30)) == wb_type
    assert wb_type.assign(4) == InvalidType()


def test_list_type():
    assert ListType(int).assign([]) == ListType(int)
    assert ListType(int).assign([1, 2, 3]) == ListType(int)
    assert ListType(int).assign([1, "a", 3]) == InvalidType()


def test_dict_type():
    spec = {"number": float, "nested": {"list_str": [str],}}
    exact = {"number": 1, "nested": {"list_str": ["hello", "world"],}}
    subset = {"nested": {"list_str": ["hi"]}}
    narrow = {"number": 1, "string": "hi"}

    wb_type = TypeRegistry.type_of(exact)
    assert wb_type.assign(exact) == wb_type
    assert wb_type.assign(subset) == InvalidType()
    assert wb_type.assign(narrow) == InvalidType()

    spec = {
        "optional_number": OptionalType(float),
        "optional_unknown": OptionalType(UnknownType()),
    }

    wb_type = DictType(spec)
    assert wb_type.assign({}) == wb_type
    assert wb_type.assign({"optional_number": 1}) == wb_type
    assert wb_type.assign({"optional_number": "1"}) == InvalidType()
    assert wb_type.assign({"optional_unknown": "hi"}) == DictType(
        {"optional_number": OptionalType(float), "optional_unknown": OptionalType(str),}
    )
    assert wb_type.assign({"optional_unknown": None}) == DictType(
        {
            "optional_number": OptionalType(float),
            "optional_unknown": OptionalType(UnknownType()),
        }
    )

    wb_type = DictType({"unknown": UnknownType()})
    assert wb_type.assign({}) == InvalidType()
    assert wb_type.assign({"unknown": None}) == InvalidType()
    assert wb_type.assign({"unknown": 1}) == DictType({"unknown": float},)


def test_nested_dict():
    notation_type = DictType(
        {
            "a": float,
            "b": bool,
            "c": str,
            "d": UnknownType(),
            "e": {},
            "f": [],
            "g": [
                [
                    {
                        "a": float,
                        "b": bool,
                        "c": str,
                        "d": UnknownType(),
                        "e": {},
                        "f": [],
                        "g": [[]],
                    }
                ]
            ],
        }
    )
    expanded_type = DictType(
        {
            "a": NumberType(),
            "b": BooleanType(),
            "c": StringType(),
            "d": UnknownType(),
            "e": DictType({}),
            "f": ListType(),
            "g": ListType(
                ListType(
                    DictType(
                        {
                            "a": NumberType(),
                            "b": BooleanType(),
                            "c": StringType(),
                            "d": UnknownType(),
                            "e": DictType({}),
                            "f": ListType(),
                            "g": ListType(ListType()),
                        }
                    )
                )
            ),
        }
    )

    example = {
        "a": 1,
        "b": True,
        "c": "StringType()",
        "d": "hi",
        "e": {},
        "f": [1],
        "g": [
            [
                {
                    "a": 2,
                    "b": False,
                    "c": "StringType()",
                    "d": 3,
                    "e": {},
                    "f": [],
                    "g": [[5]],
                }
            ]
        ],
    }
    real_type = DictType.from_obj(example)

    assert notation_type == expanded_type
    assert notation_type.assign(example) == real_type


def test_image_type():
    wb_type = data_types._ImageType()
    image_simple = data_types.Image(np.random.rand(10, 10))
    wb_type_simple = data_types._ImageType.from_obj(image_simple)
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
    wb_type_annotated = data_types._ImageType.from_obj(image_annotated)

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
    assert wb_type_annotated.assign(image_simple) == InvalidType()
    assert wb_type_annotated.assign(image_annotated_differently) == InvalidType()


def test_classes_type():
    wb_classes = data_types.Classes(
        [
            {"id": 1, "name": "cat"},
            {"id": 2, "name": "dog"},
            {"id": 3, "name": "horse"},
        ]
    )

    wb_class_type = data_types._ClassesIdType.from_obj(wb_classes)
    assert wb_class_type.assign(1) == wb_class_type
    assert wb_class_type.assign(0) == InvalidType()


def test_table_type():
    table_1 = wandb.Table(columns=["col"], data=[[1]])
    t1 = data_types._TableType.from_obj(table_1)
    table_2 = wandb.Table(columns=["col"], data=[[1.3]])
    table_3 = wandb.Table(columns=["col"], data=[["a"]])
    assert t1.assign(table_2) == t1
    assert t1.assign(table_3) == InvalidType()


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
    table = wandb.Table(columns=["a", "b"], dtype=int)
    table.add_data(None, None)
    table.add_data(1, 2)
    with pytest.raises(TypeError):
        table.add_data(1, "a")

    table = wandb.Table(columns=["a", "b"], optional=False, dtype=[int, str])
    with pytest.raises(TypeError):
        table.add_data(None, None)
    table.add_data(1, "a")
    with pytest.raises(TypeError):
        table.add_data("a", "a")

    table = wandb.Table(columns=["a", "b"], optional=[False, True], dtype=[int, str])
    with pytest.raises(TypeError):
        table.add_data(None, None)
    with pytest.raises(TypeError):
        table.add_data(None, "a")
    table.add_data(1, None)
    table.add_data(1, "a")
    with pytest.raises(TypeError):
        table.add_data("a", "a")


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

    table.cast("type_col", wb_classes.get_type())
    table.add_data(2)

    with pytest.raises(TypeError):
        table.add_data(4)


box_annotation = {
    "box_predictions": {
        "box_data": [
            {
                "position": {"minX": 0.1, "maxX": 0.2, "minY": 0.3, "maxY": 0.4,},
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
                "position": {"minX": 0.1, "maxX": 0.2, "minY": 0.3, "maxY": 0.4,},
                "class_id": 1,
                "box_caption": "minMax(pixel)",
                "scores": {"acc": 0.1, "loss": 1.2},
            },
        ],
        "class_labels": class_labels,
    },
}
mask_annotation = {
    "mask_predictions": {
        "mask_data": np.random.randint(0, 4, size=(30, 30)),
        "class_labels": class_labels,
    },
    "mask_ground_truth": {"path": im_path, "class_labels": class_labels},
}


def test_table_specials():
    table = wandb.Table(
        columns=["image", "table"],
        optional=False,
        dtype=[data_types.Image, data_types.Table],
    )
    with pytest.raises(TypeError):
        table.add_data(None, None)

    # Infers specific types from first valid row
    table.add_data(
        data_types.Image(
            np.random.rand(10, 10), boxes=box_annotation, masks=mask_annotation,
        ),
        data_types.Table(data=[[1, True, None]]),
    )

    # Denies conflict
    with pytest.raises(TypeError):
        table.add_data(
            data_types.Image(np.random.rand(10, 10),),
            data_types.Table(data=[[1, True, None]]),
        )

    # Denies conflict
    with pytest.raises(TypeError):
        table.add_data(
            data_types.Image(
                np.random.rand(10, 10), boxes=box_annotation, masks=mask_annotation,
            ),
            data_types.Table(data=[[1, "True", None]]),
        )

    # allows further refinement
    table.add_data(
        data_types.Image(
            np.random.rand(10, 10), boxes=box_annotation, masks=mask_annotation,
        ),
        data_types.Table(data=[[1, True, 1]]),
    )

    # allows addition
    table.add_data(
        data_types.Image(
            np.random.rand(10, 10), boxes=box_annotation, masks=mask_annotation,
        ),
        data_types.Table(data=[[1, True, 1]]),
    )


# def test_print():
#     image_annotated = data_types.Image(
#         np.random.rand(10, 10),
#         boxes={
#             "box_predictions": {
#                 "box_data": [
#                     {
#                         "position": {
#                             "minX": 0.1,
#                             "maxX": 0.2,
#                             "minY": 0.3,
#                             "maxY": 0.4,
#                         },
#                         "class_id": 1,
#                         "box_caption": "minMax(pixel)",
#                         "scores": {"acc": 0.1, "loss": 1.2},
#                     },
#                 ],
#                 "class_labels": class_labels,
#             },
#             "box_ground_truth": {
#                 "box_data": [
#                     {
#                         "position": {
#                             "minX": 0.1,
#                             "maxX": 0.2,
#                             "minY": 0.3,
#                             "maxY": 0.4,
#                         },
#                         "class_id": 1,
#                         "box_caption": "minMax(pixel)",
#                         "scores": {"acc": 0.1, "loss": 1.2},
#                     },
#                 ],
#                 "class_labels": class_labels,
#             },
#         },
#         masks={
#             "mask_predictions": {
#                 "mask_data": np.random.randint(0, 4, size=(30, 30)),
#                 "class_labels": class_labels,
#             },
#             "mask_ground_truth": {"path": im_path, "class_labels": class_labels},
#         },
#     )

#     wb_type = DictType(
#         {
#             "InvalidType": InvalidType,
#             "UnknownType": UnknownType(),
#             "AnyType": AnyType(),
#             "NoneType": None,
#             "StringType": str,
#             "NumberType": int,
#             "BooleanType": bool,
#             "Simple_ListType": ListType(int),
#             "Nested_ListType": ListType({"key": int}),
#             "UnionType": UnionType([int, str, bool]),
#             "ObjectType": ObjectType(np.array([])),
#             "ConstType": ConstType(5),
#             "ConstType_Set": ConstType(set([1, 2, 3])),
#             "OptionalType": OptionalType(int),
#             "ImageType": data_types.Image,
#             "Defined_ImageType": data_types._ImageType.from_obj(image_annotated),
#             "TableType": data_types.Table,
#             "Defined_TableType": data_types._TableType.from_obj(
#                 wandb.Table(
#                     columns=["a", "b", "c"],
#                     optional=True,
#                     dtype=[int, bool, str],
#                 )
#             ),
#             "ClassType": data_types._ClassesIdType.from_obj(
#                 wandb.Classes(
#                     [
#                         {"id": 1, "name": "cat"},
#                         {"id": 2, "name": "dog"},
#                         {"id": 3, "name": "horse"},
#                     ]
#                 )
#             ),
#         }
#     )

#     print(wb_type.to_json())
#     assert False
