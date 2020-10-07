import wandb


def line(table, x, y, stroke=None, title=None):
    return wandb.plot_table(
        'wandb/line/v0',
        table,
        {'x': x, 'y': y, 'stroke': stroke},
        {'title': title})
