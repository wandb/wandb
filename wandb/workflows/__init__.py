from wandb import util

reset_path = util.vendor_setup()

import model_registry as model_registry

reset_path()

__all__ = ["model_registry"]
