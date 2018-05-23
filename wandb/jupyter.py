import wandb


class Run(object):
    def __init__(self, run=None):
        self.run = run or wandb.run

    def _repr_html_(self):
        url = self.run.get_url()+"?jupyter=true"
        return '''<iframe src="%s" style="border:none;width:100%%;height:420px">
        </iframe>''' % url
