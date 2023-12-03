import dataclasses
from typing import Any, Dict, Generic, Type, TypeVar

import pytest
import wandb.apis.reports2 as wr2
from polyfactory.factories import DataclassFactory
from polyfactory.pytest_plugin import register_fixture
from pydantic import AnyUrl
from wandb.apis.reports2.interface import BlockTypes  # noqa

block_type_instance = wr2.H1

T = TypeVar("T")


class CustomDataclassFactory(Generic[T], DataclassFactory[T]):
    __is_base_factory__ = True

    @classmethod
    def get_provider_map(cls) -> Dict[Type, Any]:
        providers_map = super().get_provider_map()

        return {
            "TextLikeField": lambda: "",
            "BlockTypes": lambda: wr2.H1(),
            "PanelTypes": lambda: wr2.LinePlot(),
            "FilterExpr": lambda: "a > 1",
            AnyUrl: lambda: "https://link.com",
            **providers_map,
        }


@register_fixture
class H1Factory(CustomDataclassFactory[wr2.H1]):
    __model__ = wr2.H1


@register_fixture
class H2Factory(CustomDataclassFactory[wr2.H2]):
    __model__ = wr2.H2


@register_fixture
class H3Factory(CustomDataclassFactory[wr2.H3]):
    __model__ = wr2.H3


@register_fixture
class BlockQuoteFactory(CustomDataclassFactory[wr2.BlockQuote]):
    __model__ = wr2.BlockQuote


@register_fixture
class CalloutBlockFactory(CustomDataclassFactory[wr2.CalloutBlock]):
    __model__ = wr2.CalloutBlock


@register_fixture
class CheckedListFactory(CustomDataclassFactory[wr2.CheckedList]):
    __model__ = wr2.CheckedList


@register_fixture
class CodeBlockFactory(CustomDataclassFactory[wr2.CodeBlock]):
    __model__ = wr2.CodeBlock


@register_fixture
class GalleryFactory(CustomDataclassFactory[wr2.Gallery]):
    __model__ = wr2.Gallery


@register_fixture
class HorizontalRuleFactory(CustomDataclassFactory[wr2.HorizontalRule]):
    __model__ = wr2.HorizontalRule


@register_fixture
class ImageFactory(CustomDataclassFactory[wr2.Image]):
    __model__ = wr2.Image


@register_fixture
class LatexBlockFactory(CustomDataclassFactory[wr2.LatexBlock]):
    __model__ = wr2.LatexBlock


@register_fixture
class MarkdownBlockFactory(CustomDataclassFactory[wr2.MarkdownBlock]):
    __model__ = wr2.MarkdownBlock


@register_fixture
class OrderedListFactory(CustomDataclassFactory[wr2.OrderedList]):
    __model__ = wr2.OrderedList


@register_fixture
class PFactory(CustomDataclassFactory[wr2.P]):
    __model__ = wr2.P


@register_fixture
class PanelGridFactory(CustomDataclassFactory[wr2.PanelGrid]):
    __model__ = wr2.PanelGrid


@register_fixture
class TableOfContentsFactory(CustomDataclassFactory[wr2.TableOfContents]):
    __model__ = wr2.TableOfContents


@register_fixture
class UnorderedListFactory(CustomDataclassFactory[wr2.UnorderedList]):
    __model__ = wr2.UnorderedList


@register_fixture
class VideoFactory(CustomDataclassFactory[wr2.Video]):
    __model__ = wr2.Video


block_factory_names = [
    "h1_factory",
    "h2_factory",
    "h3_factory",
    "block_quote_factory",
    "callout_block_factory",
    "checked_list_factory",
    "code_block_factory",
    "gallery_factory",
    "horizontal_rule_factory",
    "image_factory",
    "latex_block_factory",
    "markdown_block_factory",
    "ordered_list_factory",
    "p_factory",
    "panel_grid_factory",
    "table_of_contents_factory",
    "unordered_list_factory",
    "video_factory",
]


@register_fixture
class BarPlotFactory(CustomDataclassFactory[wr2.BarPlot]):
    __model__ = wr2.BarPlot


@register_fixture
class CodeComparerFactory(CustomDataclassFactory[wr2.CodeComparer]):
    __model__ = wr2.CodeComparer


@register_fixture
class CustomChartFactory(CustomDataclassFactory[wr2.CustomChart]):
    __model__ = wr2.CustomChart


@register_fixture
class LinePlotFactory(CustomDataclassFactory[wr2.LinePlot]):
    __model__ = wr2.LinePlot


@register_fixture
class MarkdownPanelFactory(CustomDataclassFactory[wr2.MarkdownPanel]):
    __model__ = wr2.MarkdownPanel


@register_fixture
class MediaBrowserFactory(CustomDataclassFactory[wr2.MediaBrowser]):
    __model__ = wr2.MediaBrowser


@register_fixture
class ParallelCoordinatesPlotFactory(
    CustomDataclassFactory[wr2.ParallelCoordinatesPlot]
):
    __model__ = wr2.ParallelCoordinatesPlot


@register_fixture
class ParameterImportancePlotFactory(
    CustomDataclassFactory[wr2.ParameterImportancePlot]
):
    __model__ = wr2.ParameterImportancePlot


@register_fixture
class RunComparerFactory(CustomDataclassFactory[wr2.RunComparer]):
    __model__ = wr2.RunComparer


@register_fixture
class ScalarChartFactory(CustomDataclassFactory[wr2.ScalarChart]):
    __model__ = wr2.ScalarChart


@register_fixture
class ScatterPlotFactory(CustomDataclassFactory[wr2.ScatterPlot]):
    __model__ = wr2.ScatterPlot


panel_factory_names = [
    "bar_plot_factory",
    "code_comparer_factory",
    "custom_chart_factory",
    "line_plot_factory",
    "markdown_panel_factory",
    "media_browser_factory",
    "parallel_coordinates_plot_factory",
    "parameter_importance_plot_factory",
    "run_comparer_factory",
    "scalar_chart_factory",
    "scatter_plot_factory",
]


def is_dataclass_instance(obj):
    return dataclasses.is_dataclass(obj) and not isinstance(obj, type)


def is_empty_or_none(val):
    return val is None or (not val and isinstance(val, (list, str, dict)))


def compare_values(val1, val2) -> bool:
    """Compare two values, which may be lists, dicts, dataclass instances, or other types."""
    if is_dataclass_instance(val1) and is_dataclass_instance(val2):
        return compare_dataclasses(val1, val2)
    elif isinstance(val1, list) and isinstance(val2, list):
        if len(val1) != len(val2):
            return False
        return all(compare_values(v1, v2) for v1, v2 in zip(val1, val2))
    elif isinstance(val1, dict) and isinstance(val2, dict):
        if val1.keys() != val2.keys():
            return False
        return all(compare_values(val1[k], val2[k]) for k in val1)
    else:
        return val1 == val2 or (is_empty_or_none(val1) and is_empty_or_none(val2))


def compare_dataclasses(dc1: Any, dc2: Any) -> bool:
    if not is_dataclass_instance(dc1) or not is_dataclass_instance(dc2):
        return False

    for field in dataclasses.fields(dc1):
        key = field.name
        value1 = getattr(dc1, key)
        value2 = getattr(dc2, key)

        if not compare_values(value1, value2):
            return False

    return True


factory_names = block_factory_names + panel_factory_names


@pytest.mark.parametrize("factory_name", factory_names)
def test_idempotency(request, factory_name) -> None:
    factory = request.getfixturevalue(factory_name)
    instance = factory.build()

    cls = factory.__model__
    assert isinstance(instance, cls)

    model = instance.to_model()
    model2 = cls.from_model(model).to_model()

    assert model.dict() == model2.dict()


def test_idempotency_from_real_reports():
    url = "https://wandb.ai/megatruong/report-api-testing/reports/Copy-of-megatruong-s-Copy-of-megatruong-s-Copy-of-megatruong-s-Copy-of-megatruong-s-Copy-of-megatruong-s-Untitled-Report--Vmlldzo2MDQyNzgw"
    vs = wr2.interface._url_to_viewspec(url)
    report = wr2.Report.from_url(url)

    assert report.to_model().dict() == vs

    # model = instance.to_model()
    # instance2 = cls.from_model(model)
    # assert compare_dataclasses(instance, instance2)


# blocks = [
#     wr2.H1,
#     wr2.H2,
#     wr2.H3,
#     wr2.BlockQuote,
#     wr2.CalloutBlock,
#     wr2.CheckedList,
#     wr2.CodeBlock,
#     wr2.Gallery,
#     wr2.HorizontalRule,
#     wr2.Image,
#     wr2.LatexBlock,
#     wr2.MarkdownBlock,
#     wr2.OrderedList,
#     wr2.P,
#     wr2.PanelGrid,
#     wr2.TableOfContents,
#     wr2.UnorderedList,
#     wr2.Video,
#     # wr2.WeaveBlock,
# ]

panels = [
    wr2.BarPlot,
    wr2.CodeComparer,
    wr2.CustomChart,
    wr2.LinePlot,
    wr2.MarkdownPanel,
    wr2.MediaBrowser,
    wr2.ParallelCoordinatesPlot,
    wr2.ParameterImportancePlot,
    wr2.RunComparer,
    wr2.ScalarChart,
    wr2.ScatterPlot,
    # wr2.WeavePanel,
]

# classes = blocks + panels


# def generate_test_data(field_type):
#     # Base types
#     if field_type == int:
#         return random.randint(1, 100)
#     elif field_type == float:
#         return round(random.uniform(1.0, 100.0), 2)
#     elif field_type == str:
#         return "test_str_" + str(random.randint(1, 100))
#     elif field_type == bool:
#         return random.choice([True, False])
#     elif field_type == TextLikeField:
#         return ""
#     elif field_type == CheckedListItem:
#         return CheckedListItem("abc", True)
#     elif field_type == UnorderedListItem:
#         return UnorderedListItem("def")
#     elif field_type == OrderedListItem:
#         return OrderedListItem("ghi")

#     # List type
#     elif get_origin(field_type) == list:
#         element_type = get_args(field_type)[0]  # Get the type of list elements
#         return [generate_test_data(element_type) for _ in range(random.randint(1, 3))]

#     # Dict type
#     elif get_origin(field_type) == dict:
#         key_type, value_type = get_args(field_type)
#         return {
#             generate_test_data(key_type): generate_test_data(value_type)
#             for _ in range(random.randint(1, 3))
#         }

#     # Add additional handling for other complex or custom types as needed

#     else:
#         # Handle unknown types
#         return None


# @pytest.mark.parametrize("cls", blocks)
# def test_interface_idempotency(cls):
#     block = cls()

#     for field in dataclasses.fields(block):
#         setattr(block, field.name, generate_test_data(field.type))

#     model = block.to_model()
#     block2 = cls.from_model(model)

#     assert block == block2


# def test_report_idempotency():
#     report = wr2.Report("test")
#     model = report.to_model()
#     report2 = wr2.Report.from_model(model)

#     assert report == report2


# # @pytest.mark.parametrize("cls", blocks)
# # def test_model_idempotency(cls):
# #     block = cls()
# #     model = block.to_model()
# #     block2 = cls.from_model(model)

# #     assert block == block2


# def test_collapsible_headings():
#     ...
