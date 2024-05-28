import sys
from typing import Any, Dict, Generic, Type, TypeVar

import pytest  # noqa: E402
import wandb.apis.workspaces as ws

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
                "FilterExpr": lambda: ws.Metric("abc") > 1,
                **providers_map,
            }

    @register_fixture
    class WorkspaceFactory(CustomDataclassFactory[ws.Workspace]):
        __model__ = ws.Workspace

        @classmethod
        def runset_settings(cls):
            return ws.RunSetSettings(
                filters=[
                    ws.Metric("abc") > 1,
                    ws.Metric("def") < 2,
                    ws.Metric("ghi") >= 3,
                    ws.Metric("jkl") <= 4,
                    ws.Metric("mno") == 5,
                    ws.Metric("pqr") != 6,
                    ws.Metric("stu").isin([7, 8, 9]),
                    ws.Metric("vwx").notin([10, 11, 12]),
                ],
            )

    @register_fixture
    class WorkspaceSettingsFactory(CustomDataclassFactory[ws.WorkspaceSettings]):
        __model__ = ws.WorkspaceSettings

    @register_fixture
    class SectionFactory(CustomDataclassFactory[ws.Section]):
        __model__ = ws.Section

    @register_fixture
    class SectionPanelSettingsFactory(CustomDataclassFactory[ws.SectionPanelSettings]):
        __model__ = ws.SectionPanelSettings


factory_names = [
    "workspace_factory",
    "workspace_settings_factory",
    "section_factory",
    "section_panel_settings_factory",
]


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


@pytest.mark.parametrize(
    "expr, spec",
    [
        (
            ws.Metric("abc") > 1,
            {
                "op": ">",
                "key": {"section": "run", "name": "abc"},
                "value": 1,
                "disabled": False,
            },
        ),
        (
            ws.Metric("Name") != "tomato",
            {
                "op": "!=",
                "key": {"section": "run", "name": "displayName"},
                "value": "tomato",
                "disabled": False,
            },
        ),
        (
            ws.Metric("Tags").isin(["ppo", "4pool"]),
            {
                "op": "IN",
                "key": {"section": "run", "name": "tags"},
                "value": ["ppo", "4pool"],
                "disabled": False,
            },
        ),
    ],
)
def test_filter_expr(expr, spec):
    assert expr.to_model().model_dump(by_alias=True, exclude_none=True) == spec
