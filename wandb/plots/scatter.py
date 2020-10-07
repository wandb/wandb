import wandb


def scatter(table, x, y, title=None):
    return wandb.plot_table(
        'wandb/scatter/v0',
        table,
        {'x': x, 'y': y},
        {'title': title})
