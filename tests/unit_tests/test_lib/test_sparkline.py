from wandb.sdk.lib import sparkline


def test_sparkline():
    assert sparkline.sparkify([1, 2, 3]) == "▁▅█"


def test_sparkline_nan():
    assert sparkline.sparkify([float("nan"), 2, 3]) == " ▁█"


def test_sparkline_inf():
    assert sparkline.sparkify([float("inf"), 2, 3]) == " ▁█"


def test_sparkline_1finite():
    assert sparkline.sparkify([float("inf"), 2, float("-inf")]) == " ▁ "


def test_sparkline_0finite():
    assert sparkline.sparkify([float("inf"), float("nan"), float("-inf")]) == ""


def test_sparkline_empty():
    assert sparkline.sparkify([]) == ""
