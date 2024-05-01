import os
import sys
from typing import Any, Dict, Generic, Type, TypeVar

os.environ["WANDB_REPORT_API_ENABLE_V2"] = "True"

import pytest  # noqa: E402
import wandb.apis.reports as wr2  # noqa: E402
from wandb.apis.reports.v2.expr_parsing import expr_to_filters  # noqa: E402
from wandb.apis.reports.v2.internal import Filters, Key  # noqa: E402

block_type_instance = wr2.H1

T = TypeVar("T")

# Polyfactory stuff is >= 3.8 only
if sys.version_info >= (3, 8):
    from polyfactory.factories import DataclassFactory
    from polyfactory.pytest_plugin import register_fixture

    class CustomDataclassFactory(Generic[T], DataclassFactory[T]):
        __is_base_factory__ = True
        # __random_seed__ = 123

        @classmethod
        def get_provider_map(cls) -> Dict[Type, Any]:
            providers_map = super().get_provider_map()

            return {
                "TextLikeField": lambda: "",
                "BlockTypes": lambda: wr2.H1(),
                "PanelTypes": lambda: wr2.LinePlot(),
                "AnyUrl": lambda: "https://link.com",
                **providers_map,
            }

    class GradientPointFactory(CustomDataclassFactory[wr2.GradientPoint]):
        __model__ = wr2.GradientPoint

        @classmethod
        def color(cls):
            return "#FFFFFF"

    class ParallelCoordinatesPlotColumnFactory(
        CustomDataclassFactory[wr2.ParallelCoordinatesPlotColumn]
    ):
        __model__ = wr2.ParallelCoordinatesPlotColumn

        @classmethod
        def metric(cls):
            return wr2.Config("test")

    @register_fixture
    class H1Factory(CustomDataclassFactory[wr2.H1]):
        __model__ = wr2.H1

        @classmethod
        def collapsed_blocks(cls):
            return None

    @register_fixture
    class H2Factory(CustomDataclassFactory[wr2.H2]):
        __model__ = wr2.H2

        @classmethod
        def collapsed_blocks(cls):
            return None

    @register_fixture
    class H3Factory(CustomDataclassFactory[wr2.H3]):
        __model__ = wr2.H3

        @classmethod
        def collapsed_blocks(cls):
            return None

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

        @classmethod
        def panels(cls):
            return [wr2.LinePlot()]

        @classmethod
        def runsets(cls):
            return [
                wr2.Runset(filters="a >= 1"),
                wr2.Runset(filters="b == 1 and c == 2"),
            ]

    @register_fixture
    class TableOfContentsFactory(CustomDataclassFactory[wr2.TableOfContents]):
        __model__ = wr2.TableOfContents

    @register_fixture
    class UnorderedListFactory(CustomDataclassFactory[wr2.UnorderedList]):
        __model__ = wr2.UnorderedList

    @register_fixture
    class VideoFactory(CustomDataclassFactory[wr2.Video]):
        __model__ = wr2.Video

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

        @classmethod
        def gradient(cls):
            return [GradientPointFactory.build()]

        @classmethod
        def columns(cls):
            return [ParallelCoordinatesPlotColumnFactory.build()]

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

        @classmethod
        def gradient(cls):
            gradient_point = GradientPointFactory.build()
            return [gradient_point]


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

factory_names = block_factory_names + panel_factory_names


@pytest.mark.skipif(
    sys.version_info < (3, 8), reason="polyfactory requires py38 or higher"
)
@pytest.mark.parametrize("factory_name", factory_names)
def test_idempotency(request, factory_name) -> None:
    factory = request.getfixturevalue(factory_name)
    instance = factory.build()

    cls = factory.__model__
    assert isinstance(instance, cls)

    model = instance.to_model()
    model2 = cls.from_model(model).to_model()

    assert model.dict() == model2.dict()


def test_fix_panel_collisions():
    p1 = wr2.interface.Panel(layout=wr2.Layout(0, 0, 8, 6))
    p2 = wr2.interface.Panel(layout=wr2.Layout(1, 1, 8, 6))
    p3 = wr2.interface.Panel(layout=wr2.Layout(2, 1, 8, 6))

    panels = [p1, p2, p3]
    panels = wr2.interface._resolve_collisions(panels)

    for p1 in panels:
        for p2 in panels[1:]:
            assert not wr2.interface._collides(p1, p2)


@pytest.mark.parametrize(
    "expr, expected_filters",
    [
        ["", []],
        [
            "a >= 1",
            [
                Filters(
                    op=">=",
                    key=Key(section="run", name="a"),
                    filters=None,
                    value=1,
                    disabled=False,
                )
            ],
        ],
        [
            "(a >= 1)",
            [
                Filters(
                    op=">=",
                    key=Key(section="run", name="a"),
                    filters=None,
                    value=1,
                    disabled=False,
                )
            ],
        ],
        [
            "(Metric('a') >= 1)",
            [
                Filters(
                    op=">=",
                    key=Key(section="run", name="a"),
                    filters=None,
                    value=1,
                    disabled=False,
                )
            ],
        ],
        [
            "(SummaryMetric('a') >= 1)",
            [
                Filters(
                    op=">=",
                    key=Key(section="summary", name="a"),
                    filters=None,
                    value=1,
                    disabled=False,
                )
            ],
        ],
        [
            "(Config('a') >= 1)",
            [
                Filters(
                    op=">=",
                    key=Key(section="config", name="a"),
                    filters=None,
                    value=1,
                    disabled=False,
                )
            ],
        ],
    ],
)
def test_expression_parsing(expr, expected_filters):
    assert expr_to_filters(expr) == Filters(
        op="OR", filters=[Filters(op="AND", filters=expected_filters)]
    )
