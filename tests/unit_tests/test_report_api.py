import inspect
from itertools import filterfalse
import os
from dataclasses import dataclass
from typing import Optional, Union

import pytest

import wandb
import wandb.apis.reports as wb
import wandb.apis.reports.util as util

from wandb.apis.reports.validators import (
    Between,
    LayoutDict,
    Length,
    OneOf,
    OrderString,
    TypeValidator,
)


@pytest.fixture
def require_report_editing():
    wandb.require("report-editing")
    yield
    del os.environ["WANDB_REQUIRE_REPORT_EDITING_V0"]


# @pytest.fixture
# def api(mock_server):
#     wandb.login(key=DUMMY_API_KEY)
#     yield wandb.Api()


@pytest.fixture
def report(mock_server, api, all_blocks):
    # TODO: mock_server works, but live_mock_server does not??

    yield wb.Report(
        project="amazing-project",
        title="An amazing title",
        description="A descriptive description",
        width="fixed",
        blocks=all_blocks,
    )


@pytest.fixture
def all_panels(mock_server, api):
    yield [
        wb.MediaBrowser(media_keys="img"),  # This panel can be flakey
        wb.MarkdownPanel(
            markdown="Hello *italic* **bold** $e=mc^2$ `something` # True"
        ),  # This panel can be flakey
        wb.LinePlot(
            title="line title",
            x="x",
            y=["y"],
            range_x=[0, 100],
            range_y=[0, 100],
            log_x=True,
            log_y=True,
            title_x="x axis title",
            title_y="y axis title",
            ignore_outliers=True,
            groupby="hyperparam1",
            groupby_aggfunc="mean",
            groupby_rangefunc="minmax",
            smoothing_factor=0.5,
            smoothing_type="gaussian",
            smoothing_show_original=True,
            max_runs_to_show=10,
            plot_type="stacked-area",
            font_size="large",
            legend_position="west",
        ),
        wb.ScatterPlot(
            title="scatter title",
            x="y",
            y="y",
            # z='x',
            range_x=[0, 0.0005],
            range_y=[0, 0.0005],
            # range_z=[0,1],
            log_x=False,
            log_y=False,
            # log_z=True,
            running_ymin=True,
            running_ymean=True,
            running_ymax=True,
            font_size="small",
            regression=True,
        ),
        wb.BarPlot(
            title="bar title",
            metrics=["x"],
            vertical=True,
            range_x=[0, 100],
            title_x="x axis title",
            title_y="y axis title",
            groupby="hyperparam1",
            groupby_aggfunc="median",
            groupby_rangefunc="stddev",
            max_runs_to_show=20,
            max_bars_to_show=3,
            font_size="auto",
        ),
        wb.ScalarChart(
            title="scalar title",
            metric="x",
            groupby_aggfunc="max",
            groupby_rangefunc="stderr",
            font_size="large",
        ),
        wb.CodeComparer(diff="split"),
        wb.ParallelCoordinatesPlot(
            columns=[
                wb.reports.PCColumn("Step"),
                wb.reports.PCColumn("hyperparam1"),
                wb.reports.PCColumn("hyperparam2"),
                wb.reports.PCColumn("x"),
                wb.reports.PCColumn("y"),
                wb.reports.PCColumn("z"),
            ],
        ),
        wb.ParameterImportancePlot(with_respect_to="hyperparam1"),
        wb.RunComparer(diff_only="split"),
    ]


@pytest.fixture
def all_blocks(mock_server, api, all_panels, runset):
    yield [
        wb.PanelGrid(
            panels=all_panels,
            runsets=[runset],
        ),
        wb.Video(url="https://www.youtube.com/embed/6riDJMI-Y8U"),
        wb.Spotify(spotify_id="5cfUlsdrdUE4dLMK7R9CFd"),
        wb.SoundCloud(url="https://api.soundcloud.com/tracks/1076901103"),
        wb.Twitter(
            embed_html='<blockquote class="twitter-tweet"><p lang="en" dir="ltr">The voice of an angel, truly. <a href="https://twitter.com/hashtag/MassEffect?src=hash&amp;ref_src=twsrc%5Etfw">#MassEffect</a> <a href="https://t.co/nMev97Uw7F">pic.twitter.com/nMev97Uw7F</a></p>&mdash; Mass Effect (@masseffect) <a href="https://twitter.com/masseffect/status/1428748886655569924?ref_src=twsrc%5Etfw">August 20, 2021</a></blockquote>\n'
        ),
        wb.P(text="Normal paragraph"),
        wb.H1(text="Heading 1"),
        wb.H2(text="Heading 2"),
        wb.H3(text="Heading 3"),
        wb.UnorderedList(items=["Bullet 1", "Bullet 2"]),
        wb.OrderedList(items=["Ordered 1", "Ordered 2"]),
        wb.CheckedList(items=["Unchecked", "Checked"], checked=[False, True]),
        wb.BlockQuote(text="Block Quote 1\nBlock Quote 2\nBlock Quote 3"),
        wb.CalloutBlock(text=["Callout 1", "Callout 2", "Callout 3"]),
        wb.HorizontalRule(),
        wb.CodeBlock(
            code=["this:", "- is", "- a", "cool:", "- yaml", "- file"],
            language="yaml",
        ),
        wb.MarkdownBlock(text="Markdown cell with *italics* and **bold** and $e=mc^2$"),
        wb.Image(
            url="https://api.wandb.ai/files/megatruong/images/projects/918598/350382db.gif",
            caption="It's a me, Pikachu",
        ),
        wb.P(
            text=[
                "here is some text, followed by",
                wb.InlineCode("select * from code in line"),
                "and then latex",
                wb.InlineLaTeX("e=mc^2"),
            ]
        ),
        wb.LaTeXBlock(text="\\gamma^2+\\theta^2=\\omega^2\n\\\\ a^2 + b^2 = c^2"),
        wb.Gallery(ids=[]),
    ]


@pytest.fixture
def runset(
    mock_server,
    api,
):
    yield wb.RunSet()


@pytest.fixture
def panel_grid(
    mock_server,
    api,
):
    yield wb.PanelGrid()


@pytest.mark.usefixtures("require_report_editing")
class TestPublicAPI:
    @pytest.mark.parametrize(
        "project,entity,blocks,result",
        [
            (None, None, None, TypeError),
            ("project", None, None, "success"),
            ("project", "entity", [], "success"),
        ],
    )
    def test_create_report(self, api, project, entity, blocks, result):
        if result == "success":
            # User must always define a project
            report = api.create_report(project=project, entity=entity, blocks=blocks)
            assert isinstance(report, wb.Report)
        else:
            with pytest.raises(result):
                report = api.create_report(
                    project=project, entity=entity, blocks=blocks
                )

    @pytest.mark.parametrize(
        "path,result",
        [
            ("entity/project/reports/name--VmlldzoxOTcxMzI2", "valid"),
            ("entity/project/name--VmlldzoxOTcxMzI2", "valid"),
            ("entity/name--VmlldzoxOTcxMzI2", ValueError),
            ("name--VmlldzoxOTcxMzI2", ValueError),
            ("VmlldzoxOTcxMzI2", ValueError),
        ],
    )
    def test_load_report(self, live_mock_server, api, path, result):
        if result == "valid":
            report = api.load_report(path)
            assert isinstance(report, wb.Report)
        else:
            with pytest.raises(result):
                report = api.load_report(path)


@pytest.mark.usefixtures("require_report_editing", "mock_server")
class TestReport:
    def test_instantiate_report(self):
        report = wb.Report(project="something")
        with pytest.raises(TypeError):
            report = wb.Report()

    @pytest.mark.parametrize("clone", [True, False])
    def test_save_report(self, report, clone):
        report2 = report.save(clone=clone)

        if clone:
            assert report2 is not report
        else:
            assert report2 is report

    @pytest.mark.parametrize(
        "new_blocks",
        [
            [wb.H1("Heading"), wb.P("Paragraph"), wb.PanelGrid()],
            [
                wb.Video(url="https://www.youtube.com/embed/6riDJMI-Y8U"),
                wb.Spotify(spotify_id="5cfUlsdrdUE4dLMK7R9CFd"),
                wb.SoundCloud(url="https://api.soundcloud.com/tracks/1076901103"),
                wb.Twitter(
                    embed_html='<blockquote class="twitter-tweet"><p lang="en" dir="ltr">The voice of an angel, truly. <a href="https://twitter.com/hashtag/MassEffect?src=hash&amp;ref_src=twsrc%5Etfw">#MassEffect</a> <a href="https://t.co/nMev97Uw7F">pic.twitter.com/nMev97Uw7F</a></p>&mdash; Mass Effect (@masseffect) <a href="https://twitter.com/masseffect/status/1428748886655569924?ref_src=twsrc%5Etfw">August 20, 2021</a></blockquote>\n'
                ),
                wb.P(text="Normal paragraph"),
                wb.H1(text="Heading 1"),
                wb.H2(text="Heading 2"),
                wb.H3(text="Heading 3"),
                wb.UnorderedList(items=["Bullet 1", "Bullet 2"]),
                wb.OrderedList(items=["Ordered 1", "Ordered 2"]),
                wb.CheckedList(items=["Unchecked", "Checked"], checked=[False, True]),
                wb.BlockQuote(text="Block Quote 1\nBlock Quote 2\nBlock Quote 3"),
                wb.CalloutBlock(text=["Callout 1", "Callout 2", "Callout 3"]),
                wb.CodeBlock(
                    code=["# python code block", "for x in range(10):", "  pass"],
                    language="python",
                ),
                wb.HorizontalRule(),
                wb.CodeBlock(
                    code=["this:", "- is", "- a", "cool:", "- yaml", "- file"],
                    language="yaml",
                ),
                wb.MarkdownBlock(
                    text="Markdown cell with *italics* and **bold** and $e=mc^2$"
                ),
                wb.Image(
                    url="https://api.wandb.ai/files/megatruong/images/projects/918598/350382db.gif",
                    caption="It's a me, Pikachu",
                ),
                wb.P(
                    text=[
                        "here is some text, followed by",
                        wb.InlineCode("select * from code in line"),
                        "and then latex",
                        wb.InlineLaTeX("e=mc^2"),
                    ]
                ),
                wb.LaTeXBlock(
                    text="\\gamma^2+\\theta^2=\\omega^2\n\\\\ a^2 + b^2 = c^2"
                ),
                wb.Gallery(ids=[]),
                wb.PanelGrid(),
                wb.WeaveBlock(
                    spec={
                        "type": "weave-panel",
                        "children": [{"text": ""}],
                        "config": {
                            "panelConfig": {
                                "exp": {
                                    "nodeType": "output",
                                    "type": {
                                        "type": "tagged",
                                        "tag": {
                                            "type": "tagged",
                                            "tag": {
                                                "type": "typedDict",
                                                "propertyTypes": {
                                                    "entityName": "string",
                                                    "projectName": "string",
                                                },
                                            },
                                            "value": {
                                                "type": "typedDict",
                                                "propertyTypes": {
                                                    "project": "project",
                                                    "artifactName": "string",
                                                },
                                            },
                                        },
                                        "value": "artifact",
                                    },
                                    "fromOp": {
                                        "name": "project-artifact",
                                        "inputs": {
                                            "project": {
                                                "nodeType": "output",
                                                "type": {
                                                    "type": "tagged",
                                                    "tag": {
                                                        "type": "typedDict",
                                                        "propertyTypes": {
                                                            "entityName": "string",
                                                            "projectName": "string",
                                                        },
                                                    },
                                                    "value": "project",
                                                },
                                                "fromOp": {
                                                    "name": "root-project",
                                                    "inputs": {
                                                        "entityName": {
                                                            "nodeType": "const",
                                                            "type": "string",
                                                            "val": "megatruong",
                                                        },
                                                        "projectName": {
                                                            "nodeType": "const",
                                                            "type": "string",
                                                            "val": "nvda-ngc",
                                                        },
                                                    },
                                                },
                                            },
                                            "artifactName": {
                                                "nodeType": "const",
                                                "type": "string",
                                                "val": "my-artifact",
                                            },
                                        },
                                    },
                                }
                            }
                        },
                    }
                ),
                wb.P(text="Wowza"),
            ],
            [
                wb.PanelGrid(
                    panels=[
                        cls()
                        for _, cls in inspect.getmembers(wb.panels)
                        if isinstance(cls, type)
                    ]
                )
            ],
            [
                wb.PanelGrid(
                    panels=[
                        cls()
                        for _, cls in inspect.getmembers(wb.panels)
                        if isinstance(cls, type)
                    ],
                    runsets=[wb.RunSet() for _ in range(10)],
                )
            ],
        ],
    )
    def test_assign_blocks_to_report(self, report, new_blocks):
        report.blocks = new_blocks

        for b, new_b in zip(report.blocks, new_blocks):
            assert b.spec == new_b.spec

    @pytest.mark.parametrize(
        "new_blocks,result",
        [
            ([wb.P(["abc", wb.InlineLaTeX("e=mc^2")])], "success"),
            ([wb.P(["abc", wb.InlineCode("for x in range(10): pass")])], "success"),
            (
                [wb.P(["abc", wb.InlineLaTeX("e=mc^2"), wb.InlineLaTeX("e=mc^2")])],
                "success",
            ),
            ([wb.P("abc"), wb.InlineLaTeX("e=mc^2")], TypeError),
            ([wb.P("abc"), wb.InlineCode("for x in range(10): pass")], TypeError),
        ],
    )
    def test_inline_blocks_must_be_inside_p_block(self, report, new_blocks, result):
        if result == "success":
            report.blocks = new_blocks
        else:
            with pytest.raises(result):
                report.blocks = new_blocks

    def test_get_blocks(self, report):
        assert all(
            isinstance(b, wandb.apis.reports.reports.Block) for b in report.blocks
        )

    def test_get_panel_grids(self, report):
        assert all(isinstance(pg, wb.PanelGrid) for pg in report.panel_grids)

    def test_get_runsets(self, report):
        assert all(
            isinstance(rs, wb.RunSet) for pg in report.panel_grids for rs in pg.runsets
        )


@pytest.mark.usefixtures("require_report_editing")
class TestRunSet:
    def test_instantiate_runset(self):
        rs = wb.RunSet()

    @pytest.mark.parametrize(
        "expr,filtermongo,filterspec",
        [
            (
                "State == 'crashed' and team == 'amazing team'",
                {
                    "$or": [
                        {
                            "$and": [
                                {"state": "crashed"},
                                {"summary_metrics.team": "amazing team"},
                            ]
                        }
                    ]
                },
                {
                    "op": "OR",
                    "filters": [
                        {
                            "op": "AND",
                            "filters": [
                                {
                                    "key": {"section": "run", "name": "state"},
                                    "op": "=",
                                    "value": "crashed",
                                },
                                {
                                    "key": {"section": "summary", "name": "team"},
                                    "op": "=",
                                    "value": "amazing team",
                                },
                            ],
                        }
                    ],
                },
            ),
            (
                "User != 'megatruong' and Runtime < 3600",
                {
                    "$or": [
                        {
                            "$and": [
                                {"username": {"$ne": "megatruong"}},
                                {"duration": {"$lt": 3600}},
                            ]
                        }
                    ]
                },
                {
                    "op": "OR",
                    "filters": [
                        {
                            "op": "AND",
                            "filters": [
                                {
                                    "key": {"section": "run", "name": "username"},
                                    "op": "!=",
                                    "value": "megatruong",
                                },
                                {
                                    "key": {"section": "run", "name": "duration"},
                                    "op": "<",
                                    "value": 3600,
                                },
                            ],
                        }
                    ],
                },
            ),
            (
                """
                a > 123 and
                        c == "the cow"
                    and Runtime == "amazing"
                    and UsingArtifact ==
                    "other thing"
                    and Name in [123,456,789]
                """,
                {
                    "$or": [
                        {
                            "$and": [
                                {"summary_metrics.a": {"$gt": 123}},
                                {"summary_metrics.c": "the cow"},
                                {"duration": "amazing"},
                                {"inputArtifacts": "other thing"},
                                {"displayName": {"$in": [123, 456, 789]}},
                            ]
                        }
                    ]
                },
                {
                    "op": "OR",
                    "filters": [
                        {
                            "op": "AND",
                            "filters": [
                                {
                                    "key": {"section": "summary", "name": "a"},
                                    "op": ">",
                                    "value": 123,
                                },
                                {
                                    "key": {"section": "summary", "name": "c"},
                                    "op": "=",
                                    "value": "the cow",
                                },
                                {
                                    "key": {"section": "run", "name": "duration"},
                                    "op": "=",
                                    "value": "amazing",
                                },
                                {
                                    "key": {"section": "run", "name": "inputArtifacts"},
                                    "op": "=",
                                    "value": "other thing",
                                },
                                {
                                    "key": {"section": "run", "name": "displayName"},
                                    "op": "IN",
                                    "value": [123, 456, 789],
                                },
                            ],
                        }
                    ],
                },
            ),
            (
                """
                person in ['a', 'b', 'c']
                and experiment_name == "amazing experiment"
                and JobType not in ['training', 'testing']
                """,
                {
                    "$or": [
                        {
                            "$and": [
                                {"summary_metrics.person": {"$in": ["a", "b", "c"]}},
                                {
                                    "summary_metrics.experiment_name": "amazing experiment"
                                },
                                {"jobType": {"$nin": ["training", "testing"]}},
                            ]
                        }
                    ]
                },
                {
                    "op": "OR",
                    "filters": [
                        {
                            "op": "AND",
                            "filters": [
                                {
                                    "key": {"section": "summary", "name": "person"},
                                    "op": "IN",
                                    "value": ["a", "b", "c"],
                                },
                                {
                                    "key": {
                                        "section": "summary",
                                        "name": "experiment_name",
                                    },
                                    "op": "=",
                                    "value": "amazing experiment",
                                },
                                {
                                    "key": {"section": "run", "name": "jobType"},
                                    "op": "NIN",
                                    "value": ["training", "testing"],
                                },
                            ],
                        }
                    ],
                },
            ),
            (
                """
                Name in ['object_detection_2', 'pose_estimation_1', 'pose_estimation_2']
                and JobType == '<null>'
                and Runtime <= 6000
                and State != None
                and User != None
                and CreatedTimestamp <= '2022-05-06'
                and Runtime >= 0
                and team != None
                and _timestamp >= 0
                """,
                {
                    "$or": [
                        {
                            "$and": [
                                {
                                    "displayName": {
                                        "$in": [
                                            "object_detection_2",
                                            "pose_estimation_1",
                                            "pose_estimation_2",
                                        ]
                                    }
                                },
                                {"jobType": "<null>"},
                                {"duration": {"$lte": 6000}},
                                {"state": {"$ne": None}},
                                {"username": {"$ne": None}},
                                {"createdAt": {"$lte": "2022-05-06"}},
                                {"duration": {"$gte": 0}},
                                {"summary_metrics.team": {"$ne": None}},
                                {"summary_metrics._timestamp": {"$gte": 0}},
                            ]
                        }
                    ]
                },
                {
                    "op": "OR",
                    "filters": [
                        {
                            "op": "AND",
                            "filters": [
                                {
                                    "key": {"section": "run", "name": "displayName"},
                                    "op": "IN",
                                    "value": [
                                        "object_detection_2",
                                        "pose_estimation_1",
                                        "pose_estimation_2",
                                    ],
                                },
                                {
                                    "key": {"section": "run", "name": "jobType"},
                                    "op": "=",
                                    "value": "<null>",
                                },
                                {
                                    "key": {"section": "run", "name": "duration"},
                                    "op": "<=",
                                    "value": 6000,
                                },
                                {
                                    "key": {"section": "run", "name": "state"},
                                    "op": "!=",
                                    "value": None,
                                },
                                {
                                    "key": {"section": "run", "name": "username"},
                                    "op": "!=",
                                    "value": None,
                                },
                                {
                                    "key": {"section": "run", "name": "createdAt"},
                                    "op": "<=",
                                    "value": "2022-05-06",
                                },
                                {
                                    "key": {"section": "run", "name": "duration"},
                                    "op": ">=",
                                    "value": 0,
                                },
                                {
                                    "key": {"section": "summary", "name": "team"},
                                    "op": "!=",
                                    "value": None,
                                },
                                {
                                    "key": {"section": "summary", "name": "_timestamp"},
                                    "op": ">=",
                                    "value": 0,
                                },
                            ],
                        }
                    ],
                },
            ),
        ],
    )
    def test_set_filters_with_python_expr(self, runset, expr, filtermongo, filterspec):
        runset.set_filters_with_python_expr(expr)
        assert runset.spec["filters"] == runset.query_generator.mongo_to_filter(
            runset.filters
        )
        assert runset.query_generator.filter_to_mongo(filterspec) == filtermongo


class TestQueryGenerators:
    def test_pm_query_generator(self, runset):
        from wandb.apis.public import PythonMongoishQueryGenerator

        gen = PythonMongoishQueryGenerator(runset)


@pytest.mark.usefixtures("require_report_editing")
class TestPanelGrid:
    def test_instantiate_panel_grid(self):
        pg = wb.PanelGrid()
        assert pg.runsets != []

    def test_assign_runsets_to_panel_grid(self, panel_grid):
        new_runsets = [wb.RunSet() for _ in range(10)]
        panel_grid.runsets = new_runsets

        for rs, new_rs in zip(panel_grid.runsets, new_runsets):
            assert rs.spec == new_rs.spec

    def test_assign_panels_to_panel_grid(self, panel_grid):
        new_panels = [wb.LinePlot() for _ in range(10)]
        panel_grid.panels = new_panels

        for p, new_p in zip(panel_grid.panels, new_panels):
            assert p.spec == new_p.spec

    def test_panels_dont_collide_after_assignment(self, panel_grid):
        new_panels = [wb.LinePlot() for _ in range(10)]
        panel_grid.panels = new_panels

        for i, p1 in enumerate(panel_grid.panels):
            for p2 in panel_grid.panels[i:]:
                assert util.collides(p1, p2) is False


@pytest.mark.usefixtures("require_report_editing")
class TestPanels:
    @pytest.mark.parametrize(
        "cls",
        [cls for _, cls in inspect.getmembers(wb.panels) if isinstance(cls, type)],
    )
    def test_instantiate_panel(self, cls):
        # attrs = {k:v for k,v in inspect.getmembers(cls)}
        Panel = cls()


class TestValidators:
    # Note: https://stackoverflow.com/questions/37888620/comparing-boolean-and-int-using-isinstance
    @pytest.mark.parametrize(
        "typ,inputs,results",
        [
            (type(None), [1, 1.0, True, None], [False, False, False, True]),
            (int, [1, 1.0, True, None], [True, False, True, False]),
            (float, [1, 1.0, True, None], [False, True, False, False]),
            (Optional[int], [1, 1.0, True, None], [True, False, True, True]),
            ((int, float), [1, 1.0, True, None], [True, True, True, False]),
            (Union[int, float], [1, 1.0, True, None], [True, True, True, False]),
            (
                Optional[Union[int, float]],
                [1, 1.0, True, None],
                [True, True, True, True],
            ),
        ],
    )
    def test_type_validator(self, typ, inputs, results):
        v = TypeValidator(typ)
        for input, valid in zip(inputs, results):
            if valid:
                v("attr_name", input)
            else:
                with pytest.raises(TypeError):
                    v("attr_name", input)

    @pytest.mark.parametrize(
        "obj,success",
        [
            (None, True),
            ({"a": 1, "b": 2}, True),
            ({1: 1, "b": 2}, False),
            ({"a": "a", "b": "b"}, False),
        ],
    )
    def test_composed_type_validator(self, obj, success):
        validators = [
            TypeValidator(Optional[dict]),
            TypeValidator(str, how="keys"),
            TypeValidator(int, how="values"),
        ]

        if success:
            for validator in validators:
                validator("attr_name", obj)
        else:
            with pytest.raises(TypeError):
                for validator in validators:
                    validator("attr_name", obj)

    @pytest.mark.parametrize(
        "options,inputs,results",
        [
            (
                ["a", "b", "c"],
                ["a", "b", "c", "ab", "abc", 1],
                [True, True, True, False, False, False],
            ),
            (
                [1, None],
                [1, 1.0, True, False, None],
                [True, True, True, False, True],
            ),
        ],
    )
    def test_oneof_validator(self, options, inputs, results):
        v = OneOf(options)
        for input, valid in zip(inputs, results):
            if valid:
                v("attr_name", input)
            else:
                with pytest.raises(ValueError):
                    v("attr_name", input)

    @pytest.mark.parametrize(
        "length,inputs,results",
        [
            (
                2,
                [
                    ["a", "b"],
                    [
                        1,
                        2,
                    ],
                    ["a", "b", "c"],
                    ["ab"],
                ],
                [True, True, False, False],
            ),
            (
                3,
                [
                    ["a", "b"],
                    [
                        1,
                        2,
                    ],
                    ["a", "b", "c"],
                    ["ab"],
                ],
                [False, False, True, False],
            ),
        ],
    )
    def test_length_validator(self, length, inputs, results):
        v = Length(length)
        for input, valid in zip(inputs, results):
            if valid:
                v("attr_name", input)
            else:
                with pytest.raises(ValueError):
                    v("attr_name", input)

    @pytest.mark.parametrize(
        "lb,ub,inputs,results",
        [
            (0, 1, [-1, 0, 0.5, 1, 2], [False, True, True, True, False]),
            (1, 10, [0, 1, 5, 10, 20], [False, True, True, True, False]),
        ],
    )
    def test_between_validator(self, lb, ub, inputs, results):
        v = Between(lb, ub)
        for input, valid in zip(inputs, results):
            if valid:
                v("attr_name", input)
            else:
                with pytest.raises(ValueError):
                    v("attr_name", input)

    @pytest.mark.parametrize(
        "input,valid",
        [
            ("col", False),
            ("+col", True),
            ("-col", True),
            (" col", False),
            (" +col", False),
            (" -col", False),
        ],
    )
    def test_orderstring_validator(self, input, valid):
        v = OrderString()
        if valid:
            v("attr_name", input)
        else:
            with pytest.raises(ValueError):
                v("attr_name", input)

    @pytest.mark.parametrize(
        "input,valid",
        [
            ({"x": 0, "y": 0, "w": 1, "h": 1}, True),
            ({"x": 5, "y": 10, "w": 7, "h": 12}, True),
            ({"x": 0, "y": 0}, False),
            ({"w": 1, "h": 1}, False),
            ({}, False),
        ],
    )
    def test_layoutdict_validator(self, input, valid):
        v = LayoutDict()
        if valid:
            v("attr_name", input)
        else:
            with pytest.raises(ValueError):
                v("attr_name", input)


class TestMisc:
    def test_requirements(self):
        from wandb.sdk.wandb_require_helpers import requires, RequiresReportEditingMixin

        @dataclass
        class Thing:
            @requires("report-editing:v0")
            def required(self):
                return 123

            def not_required(self):
                return 456

        @dataclass
        class Thing2(RequiresReportEditingMixin):
            pass

        thing = Thing()
        assert thing.not_required() == 456
        with pytest.raises(Exception):
            thing.requried()

        with pytest.raises(Exception):
            thing2 = Thing2()

        wandb.require("report-editing:v0")
        assert thing.required() == 123
        assert Thing2()

    def test_nested_get(self):
        # obj =
        ...

    def test_nested_set(self):
        ...


class TestABC:
    def test_base(self):
        from wandb.apis.reports.util import Base

        class Derived(Base):
            pass

        derived = Derived()

    def test_panel(self):
        from wandb.apis.reports.util import Panel

        class Derived(Panel):
            @property
            def view_type(self):
                return "New View"
