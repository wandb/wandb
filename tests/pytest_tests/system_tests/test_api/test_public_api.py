
import wandb

def test_delete_summary_metric_w_no_lazyload(user, test_settings):
    run = wandb.init(settings=test_settings())
    runid = run.id

    metric = "test_val"
    for i in range(10):
        wandb.log({metric:i})
    run.finish()

    run = wandb.Api().run(f"uncategorized/{runid}")
    try:
        del run.summary[metric]
        run.update()
        # after deleting the metric, accessing it again should throw an error
        run.summary[metric]
    except:
        assert True
    else:
        assert False

