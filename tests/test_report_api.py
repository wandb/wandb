import inspect
import os
from dataclasses import dataclass

import pytest

import wandb
import wandb.apis.reports as wb
import wandb.apis.reports.util as util
from tests.conftest import DUMMY_API_KEY
from tests.utils.mock_server import mock_server


@pytest.fixture
def require_report_editing():
    wandb.require("report-editing")
    yield
    del os.environ["WANDB_REQUIRE_REPORT_EDITING_V0"]


@pytest.fixture
def api(mock_server):
    wandb.login(key=DUMMY_API_KEY)
    yield wandb.Api()


@pytest.fixture
def report(mock_server):
    yield wb.Report(
        project="amazing-project",
        blocks=[
            wb.H1("An interesting heading"),
            wb.P("special text"),
            wb.PanelGrid(panels=[wb.LinePlot(), wb.BarPlot(), wb.ScalarChart()]),
        ],
    )


@pytest.fixture
def runset(mock_server):
    yield wb.RunSet()


@pytest.fixture
def panel_grid(mock_server):
    yield wb.PanelGrid()


@pytest.mark.usefixtures("require_report_editing")
class TestPublicAPI:
    def test_create_report(self, api):
        report = api.create_report(project="something")
        assert isinstance(report, wb.Report)

        with pytest.raises(TypeError):
            report = api.create_report()  # User must always define a project

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
    def test_load_report(self, api, path, result):
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
