import wandb


def histogram(table, value, title=None):
    return wandb.plot_table(
        'wandb/histogram/v0',
        table,
        {'value': value},
        {'title': title})
