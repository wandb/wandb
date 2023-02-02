import datetime

import numpy as np
import pytest
import wandb
from wandb import data_types
from wandb.sdk.data_types._dtypes import (
    AnyType,
    BooleanType,
    ConstType,
    InvalidType,
    ListType,
    NoneType,
    NumberType,
    OptionalType,
    StringType,
    TimestampType,
    TypedDictType,
    TypeRegistry,
    UnionType,
    UnknownType,
)


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


def test_timestamp_type():
    datetime_obj = datetime.datetime(2000, 12, 1)
    date_obj = datetime.date(2000, 12, 1)
    datetime64_obj = np.datetime64("2000-12-01")

    assert TypeRegistry.type_of(datetime_obj) == TimestampType()
    assert (
        TypeRegistry.type_of(datetime_obj).assign(date_obj).assign(datetime64_obj)
        == TimestampType()
    )
    assert TypeRegistry.type_of(datetime_obj).assign(None) == InvalidType()
    assert TypeRegistry.type_of(datetime_obj).assign(1) == InvalidType()


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
    assert wb_type.assign({1}) == InvalidType()
    assert wb_type.assign([]) == InvalidType()

    wb_type = ConstType({1, 2, 3})
    assert wb_type.assign(set()) == InvalidType()
    assert wb_type.assign(None) == InvalidType()
    assert wb_type.assign({1, 2, 3}) == wb_type
    assert wb_type.assign([1, 2, 3]) == InvalidType()


def test_object_type():
    wb_type = TypeRegistry.type_of(np.random.rand(30))
    assert wb_type.assign(np.random.rand(30)) == wb_type
    assert wb_type.assign(4) == InvalidType()


def test_list_type():
    assert ListType(int).assign([]) == ListType(int, 0)
    assert ListType(int).assign([1, 2, 3]) == ListType(int, 3)
    assert ListType(int).assign([1, "a", 3]) == InvalidType()


def test_dict_type():
    spec = {
        "number": float,
        "nested": {
            "list_str": [str],
        },
    }
    exact = {
        "number": 1,
        "nested": {
            "list_str": ["hello", "world"],
        },
    }
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

    wb_type = TypedDictType(spec)
    assert wb_type.assign({}) == wb_type
    assert wb_type.assign({"optional_number": 1}) == wb_type
    assert wb_type.assign({"optional_number": "1"}) == InvalidType()
    assert wb_type.assign({"optional_unknown": "hi"}) == TypedDictType(
        {
            "optional_number": OptionalType(float),
            "optional_unknown": OptionalType(str),
        }
    )
    assert wb_type.assign({"optional_unknown": None}) == TypedDictType(
        {
            "optional_number": OptionalType(float),
            "optional_unknown": OptionalType(UnknownType()),
        }
    )

    wb_type = TypedDictType({"unknown": UnknownType()})
    assert wb_type.assign({}) == InvalidType()
    assert wb_type.assign({"unknown": None}) == InvalidType()
    assert wb_type.assign({"unknown": 1}) == TypedDictType(
        {"unknown": float},
    )


def test_nested_dict():
    notation_type = TypedDictType(
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
    expanded_type = TypedDictType(
        {
            "a": NumberType(),
            "b": BooleanType(),
            "c": StringType(),
            "d": UnknownType(),
            "e": TypedDictType({}),
            "f": ListType(),
            "g": ListType(
                ListType(
                    TypedDictType(
                        {
                            "a": NumberType(),
                            "b": BooleanType(),
                            "c": StringType(),
                            "d": UnknownType(),
                            "e": TypedDictType({}),
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
    real_type = TypedDictType.from_obj(example)

    assert notation_type == expanded_type
    assert notation_type.assign(example) == real_type


def test_image_type(assets_path):
    class_labels = {1: "tree", 2: "car", 3: "road"}
    wb_type = data_types._ImageFileType()
    image_simple = data_types.Image(np.random.rand(10, 10))
    wb_type_simple = data_types._ImageFileType.from_obj(image_simple)
    im_path = assets_path("test.png")
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
    wb_type_annotated = data_types._ImageFileType.from_obj(image_annotated)

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
    # OK to assign Images with disjoint class set
    assert wb_type_annotated.assign(image_simple) == wb_type_annotated
    # Merge when disjoint
    assert wb_type_annotated.assign(
        image_annotated_differently
    ) == data_types._ImageFileType(
        box_layers={"box_predictions": {1, 2, 3}, "box_ground_truth": {1, 2, 3}},
        box_score_keys={"loss", "acc"},
        mask_layers={
            "mask_ground_truth_2": set(),
            "mask_ground_truth": set(),
            "mask_predictions": {1, 2, 3},
        },
        class_map={"1": "tree", "2": "car", "3": "road"},
    )


def test_classes_type():
    wb_classes = data_types.Classes(
        [
            {"id": 1, "name": "cat"},
            {"id": 2, "name": "dog"},
            {"id": 3, "name": "horse"},
        ]
    )

    wb_class_type = (
        wandb.wandb_sdk.data_types.helper_types.classes._ClassesIdType.from_obj(
            wb_classes
        )
    )
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


def test_table_allow_mixed_types():
    table = wandb.Table(columns=["col"], allow_mixed_types=True)
    table.add_data(None)
    table.add_data(1)
    table.add_data("a")  # No error with allow_mixed_types

    table = wandb.Table(columns=["col"], optional=False, allow_mixed_types=True)
    with pytest.raises(TypeError):
        table.add_data(None)  # Still errors since optional is false
    table.add_data(1)
    table.add_data("a")  # No error with allow_mixed_types


def test_tables_with_dicts():
    good_data = [
        [None],
        [
            {
                "a": [
                    {
                        "b": 1,
                        "c": [
                            [
                                {
                                    "d": 1,
                                    "e": wandb.Image(
                                        np.random.randint(255, size=(10, 10))
                                    ),
                                }
                            ]
                        ],
                    }
                ]
            }
        ],
        [
            {
                "a": [
                    {
                        "b": 1,
                        "c": [
                            [
                                {
                                    "d": 1,
                                    "e": wandb.Image(
                                        np.random.randint(255, size=(10, 10))
                                    ),
                                }
                            ]
                        ],
                    }
                ]
            }
        ],
    ]
    bad_data = [
        [None],
        [
            {
                "a": [
                    {
                        "b": 1,
                        "c": [
                            [
                                {
                                    "d": 1,
                                    "e": wandb.Image(
                                        np.random.randint(255, size=(10, 10))
                                    ),
                                }
                            ]
                        ],
                    }
                ]
            }
        ],
        [
            {
                "a": [
                    {
                        "b": 1,
                        "c": [
                            [
                                {
                                    "d": 1,
                                }
                            ]
                        ],
                    }
                ]
            }
        ],
    ]

    _ = wandb.Table(columns=["A"], data=good_data, allow_mixed_types=True)
    _ = wandb.Table(columns=["A"], data=bad_data, allow_mixed_types=True)
    _ = wandb.Table(columns=["A"], data=good_data)
    with pytest.raises(TypeError):
        _ = wandb.Table(columns=["A"], data=bad_data)


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


def test_table_specials(assets_path):
    class_labels = {1: "tree", 2: "car", 3: "road"}
    im_path = assets_path("test.png")

    box_annotation = {
        "box_predictions": {
            "box_data": [
                {
                    "position": {"minX": 0.1, "maxX": 0.2, "minY": 0.3, "maxY": 0.4},
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
    }
    mask_annotation = {
        "mask_predictions": {
            "mask_data": np.random.randint(0, 4, size=(30, 30)),
            "class_labels": class_labels,
        },
        "mask_ground_truth": {"path": im_path, "class_labels": class_labels},
    }

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
            np.random.rand(10, 10),
            boxes=box_annotation,
            masks=mask_annotation,
        ),
        data_types.Table(data=[[1, True, None]]),
    )

    # Denies conflict
    with pytest.raises(TypeError):
        table.add_data(
            "hello",
            data_types.Table(data=[[1, True, None]]),
        )

    # Denies conflict
    with pytest.raises(TypeError):
        table.add_data(
            data_types.Image(
                np.random.rand(10, 10),
                boxes=box_annotation,
                masks=mask_annotation,
            ),
            data_types.Table(data=[[1, "True", None]]),
        )

    # allows further refinement
    table.add_data(
        data_types.Image(
            np.random.rand(10, 10),
            boxes=box_annotation,
            masks=mask_annotation,
        ),
        data_types.Table(data=[[1, True, 1]]),
    )

    # allows addition
    table.add_data(
        data_types.Image(
            np.random.rand(10, 10),
            boxes=box_annotation,
            masks=mask_annotation,
        ),
        data_types.Table(data=[[1, True, 1]]),
    )


def test_nan_non_float():
    import pandas as pd

    wandb.Table(dataframe=pd.DataFrame(data=[["A"], [np.nan]], columns=["a"]))


def test_table_typing_numpy():
    # Pulled from https://numpy.org/devdocs/user/basics.types.html

    # Numerics
    table = wandb.Table(columns=["A"], dtype=[NumberType])
    table.add_data(None)
    table.add_data(42)
    table.add_data(np.byte(1))
    table.add_data(np.short(42))
    table.add_data(np.ushort(42))
    table.add_data(np.intc(42))
    table.add_data(np.uintc(42))
    table.add_data(np.int_(42))
    table.add_data(np.uint(42))
    table.add_data(np.longlong(42))
    table.add_data(np.ulonglong(42))
    table.add_data(np.half(42))
    table.add_data(np.float16(42))
    table.add_data(np.single(42))
    table.add_data(np.double(42))
    table.add_data(np.longdouble(42))
    table.add_data(np.csingle(42))
    table.add_data(np.cdouble(42))
    table.add_data(np.clongdouble(42))
    table.add_data(np.int8(42))
    table.add_data(np.int16(42))
    table.add_data(np.int32(42))
    table.add_data(np.int64(42))
    table.add_data(np.uint8(42))
    table.add_data(np.uint16(42))
    table.add_data(np.uint32(42))
    table.add_data(np.uint64(42))
    table.add_data(np.intp(42))
    table.add_data(np.uintp(42))
    table.add_data(np.float32(42))
    table.add_data(np.float64(42))
    table.add_data(np.float_(42))
    table.add_data(np.complex64(42))
    table.add_data(np.complex128(42))
    table.add_data(np.complex_(42))

    # Booleans
    table = wandb.Table(columns=["A"], dtype=[BooleanType])
    table.add_data(None)
    table.add_data(True)
    table.add_data(False)
    table.add_data(np.bool_(True))

    # Array of Numerics
    table = wandb.Table(columns=["A"], dtype=[[NumberType]])
    table.add_data(None)
    table.add_data([42])
    table.add_data(np.array([1, 0], dtype=np.byte))
    table.add_data(np.array([42, 42], dtype=np.short))
    table.add_data(np.array([42, 42], dtype=np.ushort))
    table.add_data(np.array([42, 42], dtype=np.intc))
    table.add_data(np.array([42, 42], dtype=np.uintc))
    table.add_data(np.array([42, 42], dtype=np.int_))
    table.add_data(np.array([42, 42], dtype=np.uint))
    table.add_data(np.array([42, 42], dtype=np.longlong))
    table.add_data(np.array([42, 42], dtype=np.ulonglong))
    table.add_data(np.array([42, 42], dtype=np.half))
    table.add_data(np.array([42, 42], dtype=np.float16))
    table.add_data(np.array([42, 42], dtype=np.single))
    table.add_data(np.array([42, 42], dtype=np.double))
    table.add_data(np.array([42, 42], dtype=np.longdouble))
    table.add_data(np.array([42, 42], dtype=np.csingle))
    table.add_data(np.array([42, 42], dtype=np.cdouble))
    table.add_data(np.array([42, 42], dtype=np.clongdouble))
    table.add_data(np.array([42, 42], dtype=np.int8))
    table.add_data(np.array([42, 42], dtype=np.int16))
    table.add_data(np.array([42, 42], dtype=np.int32))
    table.add_data(np.array([42, 42], dtype=np.int64))
    table.add_data(np.array([42, 42], dtype=np.uint8))
    table.add_data(np.array([42, 42], dtype=np.uint16))
    table.add_data(np.array([42, 42], dtype=np.uint32))
    table.add_data(np.array([42, 42], dtype=np.uint64))
    table.add_data(np.array([42, 42], dtype=np.intp))
    table.add_data(np.array([42, 42], dtype=np.uintp))
    table.add_data(np.array([42, 42], dtype=np.float32))
    table.add_data(np.array([42, 42], dtype=np.float64))
    table.add_data(np.array([42, 42], dtype=np.float_))
    table.add_data(np.array([42, 42], dtype=np.complex64))
    table.add_data(np.array([42, 42], dtype=np.complex128))
    table.add_data(np.array([42, 42], dtype=np.complex_))

    # Array of Booleans
    table = wandb.Table(columns=["A"], dtype=[[BooleanType]])
    table.add_data(None)
    table.add_data([True])
    table.add_data([False])
    table.add_data(np.array([True, False], dtype=np.bool_))

    # Nested arrays
    table = wandb.Table(columns=["A"])
    table.add_data([[[[1, 2, 3]]]])
    table.add_data(np.array([[[[1, 2, 3]]]]))


def test_table_typing_pandas():
    import pandas as pd

    # TODO: Pandas https://pandas.pydata.org/pandas-docs/stable/user_guide/basics.html#basics-dtypes
    # Numerics
    table = wandb.Table(dataframe=pd.DataFrame([[1], [0]]).astype(np.byte))
    table.add_data(1)
    table = wandb.Table(dataframe=pd.DataFrame([[42], [42]]).astype(np.short))
    table.add_data(42)
    table = wandb.Table(dataframe=pd.DataFrame([[42], [42]]).astype(np.ushort))
    table.add_data(42)
    table = wandb.Table(dataframe=pd.DataFrame([[42], [42]]).astype(np.intc))
    table.add_data(42)
    table = wandb.Table(dataframe=pd.DataFrame([[42], [42]]).astype(np.uintc))
    table.add_data(42)
    table = wandb.Table(dataframe=pd.DataFrame([[42], [42]]).astype(np.int_))
    table.add_data(42)
    table = wandb.Table(dataframe=pd.DataFrame([[42], [42]]).astype(np.uint))
    table.add_data(42)
    table = wandb.Table(dataframe=pd.DataFrame([[42], [42]]).astype(np.longlong))
    table.add_data(42)
    table = wandb.Table(dataframe=pd.DataFrame([[42], [42]]).astype(np.ulonglong))
    table.add_data(42)
    table = wandb.Table(dataframe=pd.DataFrame([[42], [42]]).astype(np.half))
    table.add_data(42)
    table = wandb.Table(dataframe=pd.DataFrame([[42], [42]]).astype(np.float16))
    table.add_data(42)
    table = wandb.Table(dataframe=pd.DataFrame([[42], [42]]).astype(np.single))
    table.add_data(42)
    table = wandb.Table(dataframe=pd.DataFrame([[42], [42]]).astype(np.double))
    table.add_data(42)
    table = wandb.Table(dataframe=pd.DataFrame([[42], [42]]).astype(np.longdouble))
    table.add_data(42)
    table = wandb.Table(dataframe=pd.DataFrame([[42], [42]]).astype(np.csingle))
    table.add_data(42)
    table = wandb.Table(dataframe=pd.DataFrame([[42], [42]]).astype(np.cdouble))
    table.add_data(42)
    table = wandb.Table(dataframe=pd.DataFrame([[42], [42]]).astype(np.clongdouble))
    table.add_data(42)
    table = wandb.Table(dataframe=pd.DataFrame([[42], [42]]).astype(np.int8))
    table.add_data(42)
    table = wandb.Table(dataframe=pd.DataFrame([[42], [42]]).astype(np.int16))
    table.add_data(42)
    table = wandb.Table(dataframe=pd.DataFrame([[42], [42]]).astype(np.int32))
    table.add_data(42)
    table = wandb.Table(dataframe=pd.DataFrame([[42], [42]]).astype(np.int64))
    table.add_data(42)
    table = wandb.Table(dataframe=pd.DataFrame([[42], [42]]).astype(np.uint8))
    table.add_data(42)
    table = wandb.Table(dataframe=pd.DataFrame([[42], [42]]).astype(np.uint16))
    table.add_data(42)
    table = wandb.Table(dataframe=pd.DataFrame([[42], [42]]).astype(np.uint32))
    table.add_data(42)
    table = wandb.Table(dataframe=pd.DataFrame([[42], [42]]).astype(np.uint64))
    table.add_data(42)
    table = wandb.Table(dataframe=pd.DataFrame([[42], [42]]).astype(np.intp))
    table.add_data(42)
    table = wandb.Table(dataframe=pd.DataFrame([[42], [42]]).astype(np.uintp))
    table.add_data(42)
    table = wandb.Table(dataframe=pd.DataFrame([[42], [42]]).astype(np.float32))
    table.add_data(42)
    table = wandb.Table(dataframe=pd.DataFrame([[42], [42]]).astype(np.float64))
    table.add_data(42)
    table = wandb.Table(dataframe=pd.DataFrame([[42], [42]]).astype(np.float_))
    table.add_data(42)
    table = wandb.Table(dataframe=pd.DataFrame([[42], [42]]).astype(np.complex64))
    table.add_data(42)
    table = wandb.Table(dataframe=pd.DataFrame([[42], [42]]).astype(np.complex128))
    table.add_data(42)
    table = wandb.Table(dataframe=pd.DataFrame([[42], [42]]).astype(np.complex_))
    table.add_data(42)

    # Boolean
    table = wandb.Table(dataframe=pd.DataFrame([[True], [False]]).astype(np.bool_))
    table.add_data(True)

    # String aliased
    table = wandb.Table(dataframe=pd.DataFrame([[42], [42]]).astype("Int8"))
    table.add_data(42)
    table = wandb.Table(dataframe=pd.DataFrame([[42], [42]]).astype("Int16"))
    table.add_data(42)
    table = wandb.Table(dataframe=pd.DataFrame([[42], [42]]).astype("Int32"))
    table.add_data(42)
    table = wandb.Table(dataframe=pd.DataFrame([[42], [42]]).astype("Int64"))
    table.add_data(42)
    table = wandb.Table(dataframe=pd.DataFrame([[42], [42]]).astype("UInt8"))
    table.add_data(42)
    table = wandb.Table(dataframe=pd.DataFrame([[42], [42]]).astype("UInt16"))
    table.add_data(42)
    table = wandb.Table(dataframe=pd.DataFrame([[42], [42]]).astype("UInt32"))
    table.add_data(42)
    table = wandb.Table(dataframe=pd.DataFrame([[42], [42]]).astype("UInt64"))
    table.add_data(42)

    table = wandb.Table(dataframe=pd.DataFrame([["42"], ["42"]]).astype("string"))
    table.add_data("42")
    table = wandb.Table(dataframe=pd.DataFrame([[True], [False]]).astype("boolean"))
    table.add_data(True)


def test_artifact_type():
    artifact = wandb.Artifact("name", type="dataset")
    target_type = TypeRegistry.types_by_name().get("artifactVersion")()
    type_of_artifact = TypeRegistry.type_of(artifact)

    artifact_string = "wandb-artifact://test/project/astring:latest"
    type_of_artifact_string = TypeRegistry.type_of(artifact)

    artifact_config_shape = {
        "_type": "artifactVersion",
        "_version": "v0",
        "id": artifact.id,
        "version": "v0",
        "sequenceName": artifact.name.split(":")[0],
        "usedAs": "test_reference_download",
    }
    type_of_artifact_dict = TypeRegistry.type_of(artifact_config_shape)

    assert type_of_artifact.assign(artifact_string) == target_type
    assert type_of_artifact.assign(artifact_config_shape) == target_type
    assert type_of_artifact_dict.assign(artifact) == target_type
    assert type_of_artifact_dict.assign(artifact_string) == target_type
    assert type_of_artifact_string.assign(artifact_config_shape) == target_type
    assert type_of_artifact_string.assign(artifact) == target_type

    # test nested
    nested_artifact = {"nested_artifact": artifact}
    type_of_nested_artifact = TypeRegistry.type_of(nested_artifact)
    nested_artifact_string = {"nested_artifact": artifact_string}
    type_of_nested_artifact_string = TypeRegistry.type_of(nested_artifact_string)
    nested_artifact_config_dict = {"nested_artifact": artifact_config_shape}
    type_of_nested_artifact_dict = TypeRegistry.type_of(nested_artifact_config_dict)
    nested_target_type = TypedDictType(
        {"nested_artifact": TypeRegistry.types_by_name().get("artifactVersion")()}
    )
    assert type_of_nested_artifact.assign(nested_artifact_string) == nested_target_type
    assert (
        type_of_nested_artifact_dict.assign(nested_artifact_config_dict)
        == nested_target_type
    )
    assert type_of_nested_artifact_dict.assign(nested_artifact) == nested_target_type
    assert (
        type_of_nested_artifact_dict.assign(nested_artifact_string)
        == nested_target_type
    )
    assert (
        type_of_nested_artifact_string.assign(nested_artifact_config_dict)
        == nested_target_type
    )
    assert type_of_nested_artifact_string.assign(nested_artifact) == nested_target_type
