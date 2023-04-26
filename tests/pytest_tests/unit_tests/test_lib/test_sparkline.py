from wandb import wandb_lib

sparkline = wandb_lib.sparkline


def test_sparkline():
    assert sparkline.sparkify([1, 2, 3]) == "▁▅█"
