import wandb
from wandb import data_types
import numpy as np
import pytest
from wandb.dtypes import *


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
    wb_type = SetConstType(set())
    assert wb_type.assign(set()) == wb_type
    assert wb_type.assign(None) == NeverType
    assert wb_type.assign(set([1])) == NeverType
    assert wb_type.assign([]) == NeverType

    wb_type = SetConstType(set([1, 2, 3]))
    assert wb_type.assign(set()) == NeverType
    assert wb_type.assign(None) == NeverType
    assert wb_type.assign(set([1, 2, 3])) == wb_type
    assert wb_type.assign([1, 2, 3]) == NeverType


def test_object_type():
    wb_type = TypeRegistry.type_of(np.random.rand(30))
    assert wb_type.assign(np.random.rand(30)) == wb_type
    assert wb_type.assign(4) == NeverType


def test_list_type():
    assert ListType(NumberType).assign([]) == ListType(NumberType)
    assert ListType(NumberType).assign([1, 2, 3]) == ListType(NumberType)
    assert ListType(NumberType).assign([1, "a", 3]) == NeverType


def test_dict_type():
    spec = {"number": NumberType, "nested": {"list_str": ListType(TextType),}}
    exact = {"number": 1, "nested": {"list_str": ["hello", "world"],}}
    subset = {"nested": {"list_str": ["hi"]}}
    narrow = {"number": 1, "string": "hi"}

    wb_type = TypeRegistry.type_of(exact)
    assert wb_type.assign(exact) == wb_type
    assert wb_type.assign(subset) == NeverType
    assert wb_type.assign(narrow) == NeverType

    wb_type = DictType(spec, key_policy=KeyPolicy.SUBSET)
    assert wb_type.assign(exact) == wb_type
    assert wb_type.assign(subset) == wb_type
    assert wb_type.assign(narrow) == NeverType

    wb_type = DictType(spec, key_policy=KeyPolicy.UNRESTRICTED)
    combined = {
        "number": NumberType,
        "string": TextType,
        "nested": {"list_str": ListType(TextType),},
    }
    exp_type = DictType(combined, key_policy=KeyPolicy.UNRESTRICTED)
    assert wb_type.assign(exact) == wb_type
    assert wb_type.assign(subset) == wb_type
    assert wb_type.assign(narrow) == exp_type

    spec = {
        "optional_number": OptionalType(NumberType),
        "optional_unknown": OptionalType(UnknownType),
    }
    wb_type = DictType(spec, key_policy=KeyPolicy.EXACT)
    assert wb_type.assign({}) == wb_type
    assert wb_type.assign({"optional_number": 1}) == wb_type
    assert wb_type.assign({"optional_number": "1"}) == NeverType
    assert wb_type.assign({"optional_unknown": "hi"}) == DictType(
        {
            "optional_number": OptionalType(NumberType),
            "optional_unknown": OptionalType(TextType),
        },
        key_policy=KeyPolicy.EXACT,
    )
    assert wb_type.assign({"optional_unknown": None}) == DictType(
        {
            "optional_number": OptionalType(NumberType),
            "optional_unknown": OptionalType(UnknownType),
        },
        key_policy=KeyPolicy.EXACT,
    )

    wb_type = DictType({"unknown": UnknownType}, key_policy=KeyPolicy.EXACT)
    # assert wb_type.assign({}) == DictType(
    #     {"unknown": OptionalType(UnknownType)}, key_policy=KeyPolicy.EXACT
    # )
    # assert wb_type.assign({"unknown": None}) == DictType(
    #     {"unknown": OptionalType(UnknownType)}, key_policy=KeyPolicy.EXACT
    # )
    assert wb_type.assign({}) == NeverType
    assert wb_type.assign({"unknown": None}) == NeverType
    assert wb_type.assign({"unknown": 1}) == DictType(
        {"unknown": NumberType}, key_policy=KeyPolicy.EXACT
    )


def test_nested_dict():
    notation_type = DictType(
        {
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
        {
            "a": NumberType,
            "b": BooleanType,
            "c": TextType,
            "d": UnknownType,
            "e": DictType({}),
            "f": ListType(),
            "g": ListType(
                ListType(
                    DictType(
                        {
                            "a": NumberType,
                            "b": BooleanType,
                            "c": TextType,
                            "d": UnknownType,
                            "e": DictType({}),
                            "f": ListType(),
                            "g": ListType(ListType()),
                        }
                    )
                )
            ),
        }
    )

    assert notation_type == expanded_type

    notation_type = DictType(
        {
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
        {
            "a": NumberType,
            "b": BooleanType,
            "c": TextType,
            "d": UnknownType,
            "e": DictType({}, key_policy=KeyPolicy.SUBSET),
            "f": ListType(),
            "g": ListType(
                ListType(
                    DictType(
                        {
                            "a": NumberType,
                            "b": BooleanType,
                            "c": TextType,
                            "d": UnknownType,
                            "e": DictType({}, key_policy=KeyPolicy.SUBSET),
                            "f": ListType(),
                            "g": ListType(ListType()),
                        },
                        key_policy=KeyPolicy.SUBSET,
                    )
                )
            ),
        },
        key_policy=KeyPolicy.SUBSET,
    )

    # print(notation_type.to_dict())
    # print(expanded_type.to_dict())
    assert notation_type == expanded_type

    wb_type = DictType(
        {
            "l1": {
                "l2": [
                    {"a": NumberType, "b": ListType(UnknownType), "c": UnknownType,}
                ],
                "l2a": NumberType,
            }
        },
        key_policy=KeyPolicy.SUBSET,
    )
    assert wb_type.assign({}) == wb_type
    assert wb_type.assign(
        {"l1": {"l2": [{"a": 1, "b": [True], "c": "hi"}]}}
    ) == DictType(
        {
            "l1": {
                "l2": [{"a": NumberType, "b": ListType(BooleanType), "c": TextType,}],
                "l2a": NumberType,
            }
        },
        key_policy=KeyPolicy.SUBSET,
    )

    wb_type = DictType(
        {
            "l1": {
                "l2": [
                    {"a": NumberType, "b": ListType(UnknownType), "c": UnknownType,}
                ],
                "l2a": NumberType,
            }
        },
        key_policy=KeyPolicy.SUBSET,
    )
    assert wb_type.assign({"l1": {"l2": [{"b": []}]}}) == wb_type
    assert wb_type.assign({"l1": {"l2": [{"b": [1], "c": "hi"}]}}) == DictType(
        {
            "l1": {
                "l2": [{"a": NumberType, "b": ListType(NumberType), "c": TextType,}],
                "l2a": NumberType,
            }
        },
        key_policy=KeyPolicy.SUBSET,
    )
    assert wb_type.assign({"l1": {"l2": [{"a": "a",}]}}) == NeverType


# def test_table_column_types():
#     primitive_table = wandb.Table(columns=["text", "number", "boolean"])
#     primitive_table.add_data(*[None, None, None])
#     primitive_table.add_data(*["a", 1, True])
#     primitive_table.add_data(*[None, None, None])
#     primitive_table.add_data(*["b", 2, False])
#     primitive_table.add_data(*[None, None, None])
#     with pytest.raises(TypeError):
#         primitive_table.add_data(*[1, 1, True])  # should fail
#     with pytest.raises(TypeError):
#         primitive_table.add_data(*["a", "a", True])  # should fail
#     with pytest.raises(TypeError):
#         primitive_table.add_data(*["a", 1, "a"])  # should fail

#     listlike_table = wandb.Table(columns=["list_number", "list_list", "list_dict"])
#     listlike_table.add_data(*[None, None, None])
#     listlike_table.add_data(
#         *[[None, 1, None, 2], [[None, 1, None, 2]], [None, {}, None, {"a": 1}]]
#     )
#     listlike_table.add_data(*[None, None, None])
#     listlike_table.add_data(
#         *[[None, 3, None, 4], [[None, 5, None, 6]], [None, {"b": 3}, None, {"c": 1}]]
#     )
#     listlike_table.add_data(*[None, None, None])
#     with pytest.raises(TypeError):
#         listlike_table.add_data(*[1, None, None])  # should fail
#     with pytest.raises(TypeError):
#         listlike_table.add_data(*[None, 1, None])  # should fail
#     with pytest.raises(TypeError):
#         listlike_table.add_data(*[None, None, {}])  # should fail
#     with pytest.raises(TypeError):
#         listlike_table.add_data(*[[None, "a", None, 2], None, None])  # should fail
#     with pytest.raises(TypeError):
#         listlike_table.add_data(*[None, [[None, "a", None, 6]], None])  # should fail
#     with pytest.raises(TypeError):
#         listlike_table.add_data(*[None, None, [None, "a"]])  # should fail

#     obj_table = wandb.Table(columns=["dict"])
#     obj_table.add_data(*[None])
#     obj_table.add_data(*[{}])
#     obj_table.add_data(*[None])
#     obj_table.add_data(*[{"a": 1}])
#     obj_table.add_data(*[None])
#     obj_table.add_data(*[{1: 1}])
#     with pytest.raises(TypeError):
#         obj_table.add_data(*[1])  # should fail
#     with pytest.raises(TypeError):
#         obj_table.add_data(*[""])  # should fail
#     with pytest.raises(TypeError):
#         obj_table.add_data(*[[{}]])  # should fail

#     class_labels = {1: "tree", 2: "car", 3: "road"}
#     test_folder = os.path.dirname(os.path.realpath(__file__))
#     im_path = os.path.join(test_folder, "..", "assets", "test.png")
#     simple_image = wandb.Image(im_path,)
#     boxes_image = wandb.Image(
#         im_path,
#         boxes={
#             "predictions": {
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
#             "ground_truth": {
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
#     )
#     mask_image = wandb.Image(
#         im_path,
#         masks={
#             "predictions": {
#                 "mask_data": np.random.randint(0, 4, size=(30, 30)),
#                 "class_labels": class_labels,
#             },
#             "ground_truth": {"path": im_path, "class_labels": class_labels},
#         },
#     )
#     rich_image = wandb.Image(
#         im_path,
#         boxes={
#             "predictions": {
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
#             "ground_truth": {
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
#             "predictions": {
#                 "mask_data": np.random.randint(0, 4, size=(30, 30)),
#                 "class_labels": class_labels,
#             },
#             "ground_truth": {"path": im_path, "class_labels": class_labels},
#         },
#     )
#     rich_image_2 = wandb.Image(
#         im_path,
#         boxes={
#             "predictions_2": {
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
#             "ground_truth_2": {
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
#             "predictions": {
#                 "mask_data": np.random.randint(0, 4, size=(30, 30)),
#                 "class_labels": class_labels,
#             },
#             "ground_truth": {"path": im_path, "class_labels": class_labels},
#         },
#     )

#     image_table = wandb.Table(
#         columns=["simple", "with_masks", "with_boxes", "with_both"]
#     )
#     image_table.add_data(None, None, None, None)
#     image_table.add_data(simple_image, mask_image, boxes_image, rich_image)
#     image_table.add_data(None, None, None, None)
#     image_table.add_data(simple_image, mask_image, boxes_image, rich_image)
#     with pytest.raises(TypeError):
#         image_table.add_data(None, simple_image, None, None)  # should fail
#     with pytest.raises(TypeError):
#         image_table.add_data(None, None, simple_image, None)  # should fail
#     with pytest.raises(TypeError):
#         image_table.add_data(None, None, None, simple_image)  # should fail
#     with pytest.raises(TypeError):
#         image_table.add_data(None, None, None, rich_image_2)  # should fail

#     mega_table = wandb.Table(columns=["primitive", "list", "obj", "image"])
#     mega_table.add_data(None, None, None, None)
#     mega_table.add_data(primitive_table, listlike_table, obj_table, image_table)
#     mega_table.add_data(None, None, None, None)
#     mega_table.add_data(primitive_table, listlike_table, obj_table, image_table)
#     with pytest.raises(TypeError):
#         image_table.add_data(None, primitive_table, None, None)  # should fail

#     with pytest.raises(TypeError):
#         image_table.add_data(None, None, primitive_table, None)  # should fail

#     with pytest.raises(TypeError):
#         image_table.add_data(None, None, None, primitive_table)  # should fail
