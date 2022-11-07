import wandb.apis.reports as wr


def analysis(title, text):
    return [wr.H1(title), wr.P(text)]
