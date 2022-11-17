import inspect
from typing import Optional, Union
from unittest import mock

import pytest
import wandb
import wandb.apis.reports as wr
from wandb import Api
from wandb.apis.reports.testing import Attr, Base
from wandb.apis.reports.util import Block, Panel, generate_name, collides
from wandb.apis.reports.validators import Between, OneOf, TypeValidator


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


@pytest.fixture
def report():
    return wr.Report(project="example-project")


@pytest.fixture
def runset():
    return wr.Runset(entity="test_entity", project="test_project", name="runset_name")


@pytest.fixture
def panel_grid():
    return wr.PanelGrid(
        runsets=[
            wr.Runset("test_entity", "test_project", "runset_name"),
            wr.Runset("another_entity", "another_project", "runset_name2"),
        ],
        panels=[
            wr.LinePlot(x="Step", y=["val_loss"]),
            wr.ScatterPlot(x="layers", y="val_loss"),
            wr.BarPlot(metrics=["metrics"]),
        ],
    )


@pytest.fixture
def saved_report():
    report = wr.Report(project="example-project").save()
    # check to see if report was created
    return report
_inline_content = [
    wr.Link("Hello", "https://url.com"),
    wr.InlineLaTeX("e=mc^2"),
    wr.InlineCode("print('Hello world!')"),
]


@pytest.fixture(
    params=_inline_content, ids=[x.__class__.__name__ for x in _inline_content]
)
def inline_content(request):
    return request.param


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


class TestReports:
    def test_create_report(self):
        report = wr.Report(project="example-project")
        report.save()
        # check for upsert report mutation

    def test_load_report(self, saved_report):
        report = wr.Report.from_url(saved_report.url)
        assert isinstance(report, wr.Report)

        for b in zip(report.blocks, saved_report.blocks):
            assert b[0].spec == b[1].spec

        for pg in zip(report.panel_grids, saved_report.panel_grids):
            assert pg[0].spec == pg[1].spec

        for rs in zip(report.runsets, saved_report.runsets):
            assert rs[0].spec == rs[1].spec

    def test_clone_report(self, report):
        report2 = report.save(clone=True)

        assert report is not report2
        assert report.id != report2.id
        assert report.name != report2.name

        assert report.spec == report2.spec

    def test_get_blocks(self, report):
        for b in report.blocks:
            assert isinstance(b, Block)

    def test_set_blocks(self, report, block):
        report.blocks = [block]
        assert len(report.blocks) == 1
        for b in report.blocks:
            assert isinstance(b, Block)

    def test_append_block(self, report, block):
        report.blocks += [block]
        assert len(report.blocks) == 3
        for b in report.blocks:
            assert isinstance(b, Block)

    def test_get_panel_grids(self, report):
        for pg in report.panel_grids:
            assert isinstance(pg, wr.PanelGrid)

    def test_get_runsets(self, report):
        for rs in report.runsets:
            assert isinstance(rs, wr.Runset)

    def test_blocks_can_be_reassigned(self, report):
        b = wr.H1(text=["Hello world!"])
        report.blocks = [b]
        b.text = ["Goodbye world!"]
        report.blocks = [b]
        assert report.blocks[0].text == b.text

    @pytest.mark.xfail
    def test_blocks_cannot_be_mutated(self, report):
        b = wr.H1(text=["Hello world!"])
        report.blocks = [b]
        b.text = ["Goodbye world!"]
        assert report.blocks[0].text == b.text

    def test_on_save_report_runsets_have_valid_project(self, report):
        pg = wr.PanelGrid()
        report.blocks = [pg]
        pg.runsets = [
            wr.Runset(),
            wr.Runset(project=None),
            wr.Runset(project="example-project"),
        ]
        report.save()
        for rs in report.runsets:
            assert rs.project is not None

    def test_on_save_report_panel_grids_have_at_least_one_runset(self, report):
        report.blocks = [wr.PanelGrid(runsets=[]), wr.PanelGrid(runsets=[])]
        report.save()
        for pg in report.panel_grids:
            assert len(pg.runsets) >= 1


class TestPanelGrids:
    def test_get_runsets(self, panel_grid):
        for rs in panel_grid.runsets:
            assert isinstance(rs, wr.Runset)

    def test_set_runsets(self, panel_grid):
        panel_grid.runsets = [wr.Runset(), wr.Runset()]
        assert len(panel_grid.runsets) == 2
        for rs in panel_grid.runsets:
            assert isinstance(rs, wr.Runset)

    def test_append_runsets(self, panel_grid):
        panel_grid.runsets += [wr.Runset(), wr.Runset()]
        assert len(panel_grid.runsets) == 4
        for rs in panel_grid.runsets:
            assert isinstance(rs, wr.Runset)

    def test_get_panels(self, panel_grid):
        for p in panel_grid.panels:
            assert isinstance(p, Panel)

    def test_set_panels(self, panel_grid):
        panel_grid.panels = [wr.LinePlot(), wr.BarPlot()]
        assert len(panel_grid.panels) == 2
        for p in panel_grid.panels:
            assert isinstance(p, Panel)

    def test_append_panels(self, panel_grid):
        panel_grid.panels += [wr.LinePlot(), wr.BarPlot()]
        assert len(panel_grid.panels) == 5
        for p in panel_grid.panels:
            assert isinstance(p, Panel)

    def test_panels_dont_collide_after_assignment(self, panel_grid):
        panel_grid.panels = [wr.LinePlot() for _ in range(10)]
        for i, p1 in enumerate(panel_grid.panels):
            for p2 in panel_grid.panels[i:]:
                assert collides(p1, p2) is False


class TestInlineContent:
    def test_paragraph(self, report, inline_content):
        b = wr.P(["Hello World", inline_content])
        report.blocks = [b]

    @pytest.mark.parametrize("cls", [wr.H1, wr.H2, wr.H3])
    def test_heading(self, cls, report, inline_content):
        b = cls(["Hello World", inline_content])
        report.blocks = [b]

    @pytest.mark.parametrize("cls", [wr.UnorderedList, wr.OrderedList, wr.CheckedList])
    def test_list(self, cls, report, inline_content):
        b = cls(["Hello World", inline_content])
        report.blocks = [b]


class TestTemplates:
    @pytest.mark.parametrize(
        "f,kwargs",
        [[wr.create_customer_landing_page, {}], [wr.create_enterprise_report, {}]],
    )
    def test_report_templates(self, f, kwargs):
        report = f(**kwargs)
        assert isinstance(report, wr.Report)

    @pytest.mark.parametrize(
        "f,kwargs", [[wr.create_example_header, {}], [wr.create_example_footer, {}]]
    )
    def test_block_templates(self, f, kwargs):
        blocks = f(**kwargs)
        for b in blocks:
            assert isinstance(b, Block)


    def test_typed(self, wandb_object):
        wandb_object.typed = "typed_value"
        assert wandb_object.spec["typed"] == "typed_value"
        with pytest.raises(TypeError):
            wandb_object.typed = 1
        assert wandb_object.spec["typed"] == "typed_value"
        assert wandb_object.typed == "typed_value"

    def test_two_paths(self, wandb_object):
        wandb_object.two_paths = [1, 2]
        assert "two_paths" not in wandb_object.spec
        assert wandb_object.spec["two1"] == 1
        assert wandb_object.spec["two2"] == 2
        assert wandb_object.two_paths == [1, 2]

    def test_nested_path(self, wandb_object):
        wandb_object.nested_path = "nested_value"
        assert wandb_object.spec["deeply"]["nested"]["example"] == "nested_value"
        assert wandb_object.nested_path == "nested_value"

    def test_two_nested_paths(self, wandb_object):
        wandb_object.two_nested_paths = ["first", "second"]
        assert "two_nested_paths" not in wandb_object.spec
        assert wandb_object.spec["deeply"]["nested"]["first"] == "first"
        assert wandb_object.spec["deeply"]["nested"]["second"] == "second"
        assert wandb_object.two_nested_paths == ["first", "second"]

    def test_validated_scalar(self, wandb_object):
        wandb_object.validated_scalar = 1
        assert wandb_object.spec["validated_scalar"] == 1

        with pytest.raises(ValueError):
            wandb_object.validated_scalar = -999
        assert wandb_object.spec["validated_scalar"] == 1
        assert wandb_object.validated_scalar == 1

    def test_validated_list(self, wandb_object):
        wandb_object.validated_list = [1, 2, 3]
        assert wandb_object.spec["validated_list"] == [1, 2, 3]

        with pytest.raises(ValueError):
            wandb_object.validated_list = [-1, -2, -3]
        assert wandb_object.spec["validated_list"] == [1, 2, 3]

        with pytest.raises(ValueError):
            wandb_object.validated_list = [1, 2, -999]
        assert wandb_object.spec["validated_list"] == [1, 2, 3]
        assert wandb_object.validated_list == [1, 2, 3]

    def test_validated_dict_keys(self, wandb_object):
        wandb_object.validated_dict = {"a": 1, "b": 2}
        assert wandb_object.spec["validated_dict"] == {"a": 1, "b": 2}

        with pytest.raises(ValueError):
            wandb_object.validated_dict = {"a": 1, "invalid_key": 2}
        assert wandb_object.spec["validated_dict"] == {"a": 1, "b": 2}
        assert wandb_object.validated_dict == {"a": 1, "b": 2}

    def test_validated_dict_values(self, wandb_object):
        wandb_object.validated_dict = {"a": 1, "b": 2}
        assert wandb_object.spec["validated_dict"] == {"a": 1, "b": 2}

        with pytest.raises(ValueError):
            wandb_object.validated_dict = {"a": 1, "b": -999}
        assert wandb_object.spec["validated_dict"] == {"a": 1, "b": 2}
        assert wandb_object.validated_dict == {"a": 1, "b": 2}

    def test_objects_with_spec(self, wandb_object, object_with_spec):
        wandb_object.objects_with_spec = [object_with_spec]
        assert wandb_object.spec["objects_with_spec"] == [object_with_spec.spec]
        assert wandb_object.objects_with_spec == [object_with_spec]


class TestTemplates:
    def test_customer_landing_page(self):
        report = wr.templates.create_customer_landing_page()
        report.save()
