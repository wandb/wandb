from wandb import wandb_config
import shortuuid  # type: ignore


def generate_id():
    # ~3t run ids (36**8)
    run_gen = shortuuid.ShortUUID(
        alphabet=list("0123456789abcdefghijklmnopqrstuvwxyz"))
    return run_gen.random(8)


class Run(object):
    def __init__(self, config=None):
        self.config = wandb_config.Config()
        self._backend = None
        self._data = dict()
        self.run_id = generate_id()
        self._step = 0

        if config:
            self.config.update(config)

    # def _repr_html_(self):
    #     url = "https://app.wandb.test/jeff/uncategorized/runs/{}".format(
    #       self.run_id)
    #     style = "border:none;width:100%;height:400px"
    #     s = "<h1>Run({})</h1><iframe src=\"{}\" style=\"{}\"></iframe>".format(
    #       self.run_id, url, style)
    #     return s

    def _repr_mimebundle_(self, include=None, exclude=None):
        url = "https://app.wandb.test/jeff/uncategorized/runs/{}".format(
            self.run_id)
        style = "border:none;width:100%;height:400px"
        note = "(include={}, exclude={})".format(include, exclude)
        s = "<h1>Run({})</h1><p>{}</p><iframe src=\"{}\" style=\"{}\"></iframe>".format(
            self.run_id, note, url, style)
        return {"text/html": s}

    def _set_backend(self, backend):
        self._backend = backend

    def log(self, data, step=None, commit=True):
        if commit:
            self._data["_step"] = self._step
            self._step += 1
            self._data.update(data)
            self._backend.send_log(self._data)
            self._data = dict()
        else:
            self._data.update(data)

    def join(self):
        self._backend.join()

    @property
    def dir(self):
        return "run_dir"

    @property
    def summary(self):
        return dict()
