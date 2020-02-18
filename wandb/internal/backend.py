import wandb


class Backend(object):
    def __init__(self, mode=None):
        pass

    def ensure_launched(self):
        """Launch backend worker if not running."""
        pass

    def server_connect(self):
        """Connect to server."""
        pass

    def server_status(self):
        """Report server status."""
        pass

    def join(self):
        pass

    def log(self, data):
        pass

    def run_update(self, data):
        pass

