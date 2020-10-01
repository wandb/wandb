import wandb
from wandb.plots._vis_ids import VIS_IDS


def scatter(table, x, y, title=None):
    return wandb.plot_table(
        VIS_IDS['scatter-plot'],
        table,
        {'x': x, 'y': y},
        {'title': title})
