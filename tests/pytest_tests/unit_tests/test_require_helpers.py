import pytest
from wandb.sdk.wandb_require_helpers import RequiresMixin, requires


def test_requirements_mixin() -> None:
    class TestClass(RequiresMixin):
        requirement = "report-editing:v0"

    class TestClass2:
        pass

    with pytest.raises(Exception):  # noqa: B017
        TestClass()

    assert TestClass2()


def test_requirements_decorator() -> None:
    @requires("report-editing:v0")
    def test_func() -> None:
        return "fail"

    def test_func2() -> None:
        return "pass"

    with pytest.raises(Exception):  # noqa: B017
        test_func()

    assert test_func2() == "pass"
