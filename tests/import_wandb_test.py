import pytest
import sys
from click.testing import CliRunner
import os

# import importlib
# import tempfile


def test_path_and_filesystem_unchanged():
    with CliRunner().isolated_filesystem():
        # wandb_dirs = ["WANDB_DIR","WANDB_RUN_DIR","WANDB_CONFIG_DIR","WANDB_CACHE_DIR"]
        # environ_cache = {}
        # target_dirs = []
        # cwd = os.getcwd()

        # # update the environment variables (and cache current ones not to mess with pytest)
        # for wandb_dir in wandb_dirs:
        #     if wandb_dir in os.environ:
        #         environ_cache[wandb_dir] = os.environ[wandb_dir]
        #     target_dir = os.path.join(tempfile.gettempdir(), wandb_dir)
        #     os.environ[wandb_dir] = target_dir
        #     target_dirs.append(target_dir)

        # # Ensure the current Working directory is empty
        # assert os.listdir(cwd) == []
        # # ensure the target dirs have not been created
        # assert all([not os.path.exists(target_dir) for target_dir in target_dirs])
        import wandb

        # import pdb; pdb.set_trace()
        # importlib.reload(wandb)
        # assert False

        # # Ensure the current Working directory is still empty
        # assert os.listdir(cwd) == []
        # # ensure the target dirs still have not been created
        # assert all([not os.path.exists(target_dir) for target_dir in target_dirs])

        # wandb.init(settings=wandb.Settings(anonymous="true"))
        # wandb.finish()

        # # ensure the target dirs have been created
        # assert all([os.path.exists(target_dir) for target_dir in target_dirs])

        # Ideally we would compare directly to the user's starting path,
        # but that seems to be mutiliated with tox. So, we check for known
        # leaks.
        for item in sys.path:
            assert "wandb/vendor" not in item

        # restore the starting environment settings
        for wandb_dir in wandb_dirs:
            if wandb_dir in environ_cache:
                os.environ[wandb_dir] = environ_cache[wandb_dir]
            elif wandb_dir in os.environ:
                del os.environ[wandb_dir]
