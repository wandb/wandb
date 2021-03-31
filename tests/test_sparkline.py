# vim: set fileencoding=utf-8 :

from wandb import wandb_lib

sparkline = wandb_lib.sparkline


def test_sparkline():
    assert sparkline.sparkify([1, 2, 3]) == u"▁▅█"


def test_sparkline_nan():
    assert sparkline.sparkify([float("nan"), 2, 3]) == u" ▁█"


def test_sparkline_inf():
    assert sparkline.sparkify([float("inf"), 2, 3]) == u" ▁█"


def test_sparkline_1finite():
    assert sparkline.sparkify([float("inf"), 2, float("-inf")]) == u" ▁ "


def test_sparkline_0finite():
    assert sparkline.sparkify([float("inf"), float("nan"), float("-inf")]) == u""


def test_sparkline_empty():
    assert sparkline.sparkify([]) == u""
