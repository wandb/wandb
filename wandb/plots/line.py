import wandb
from wandb.plots._vis_ids import VIS_IDS


def line(table, x, y, stroke=None, title=None):
    return wandb.plot_table(
        VIS_IDS['line-plot'],
        table,
        {'x': x, 'y': y, 'stroke': stroke},
        {'title': title})
