import wandb
from wandb.plots._vis_ids import VIS_IDS


def histogram(table, value, title=None):
    return wandb.plot_table(
        VIS_IDS['histogram'],
        table,
        {'value': value},
        {'title': title})
