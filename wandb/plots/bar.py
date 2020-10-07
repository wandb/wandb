import wandb


def bar(table, label, value, title=None):
    return wandb.plot_table(
        'wandb/bar/v0',
        table,
        {'label': label, 'value': value},
        {'title': title})
