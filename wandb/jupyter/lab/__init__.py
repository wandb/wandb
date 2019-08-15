import json
import os
from notebook.base.handlers import IPythonHandler
from notebook.utils import url_path_join
from .proxy import ProxyHandler, ProxyWSHandler


class IFrameHandler(IPythonHandler):
    def initialize(self, welcome=None, sites=None):
        self.sites = sites
        self.welcome = welcome

    def get(self):
        self.finish(json.dumps({'welcome': self.welcome or '', 'sites': self.sites}))


class ContextHandler(IPythonHandler):
    def initialize(self, welcome=None, sites=None):
        self.sites = sites
        self.welcome = welcome

    def post(self):
        context = self.get_json_body()
        print("CTX", context)
        home = os.path.expanduser("~")
        with open(os.path.join(home, "wandb-context.json"), "w") as f:
            f.write(json.dumps(context))

        self.finish(json.dumps(context))


def load_jupyter_server_extension(nb_server_app):
    """
    Called when the extension is loaded.

    Args:
        nb_server_app (NotebookWebApplication): handle to the Notebook webserver instance.
    """
    web_app = nb_server_app.web_app
    sites = nb_server_app.config.get('JupyterWandb', {}).get('iframes', [])
    welcome = nb_server_app.config.get('JupyterWandb', {}).get('welcome', [])

    host_pattern = '.*$'
    base_url = web_app.settings['base_url']

    nb_server_app.log.info('Installing jupyterlab_iframe handler on path %s' % url_path_join(base_url, 'iframes'))
    nb_server_app.log.info('Handling iframes: %s' % sites)

    web_app.add_handlers(host_pattern, [(url_path_join(base_url, 'wandb/'), IFrameHandler, {'welcome': welcome, 'sites': sites}),
                                        (url_path_join(base_url, 'wandb/context'), ContextHandler),
                                        (url_path_join(base_url, 'wandb/proxy'), ProxyWSHandler),
                                        ])
    nb_server_app.log.info("wandb jupyter loaded!")
