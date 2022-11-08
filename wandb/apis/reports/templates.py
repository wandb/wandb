import wandb.apis.reports as wb


def analysis(title, text):
    return [wb.H1(title), wb.P(text)]
