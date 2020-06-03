import wandb
import lightgbm as lgb


def test_types(**kwargs):
    test_passed = True
    for k, v in kwargs.items():
        if k == 'model':
            if not (isinstance(v, lgb.basic.Booster)):
                test_passed = False
                wandb.termerror("%s is not a LightGBM model. Please try again." % (k))

    return test_passed