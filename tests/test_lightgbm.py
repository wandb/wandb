import pytest
import numpy as np
import lightgbm as lgb
import wandb
import sys
from wandb import wandb_run
from wandb.lightgbm import wandb_callback

# Tests which rely on row history in memory should set `History.keep_rows = True`
from wandb.history import History
History.keep_rows = True


@pytest.fixture
def dummy_data(request):
    data = np.array([[1, 2], [3, 4]])
    label = np.array([0, 1])
    dtrain = lgb.Dataset(data, label=label)
    return dtrain

@pytest.mark.skipif(sys.version_info < (3, 6), reason="lightgbm was segfaulting in CI")
def test_basic_lightgbm(dummy_data, wandb_init_run):
    param = {'max_depth': 2, 'eta': 1}
    num_round = 2
    lgb.train(param, dummy_data, num_round, callbacks=[wandb_callback()])
