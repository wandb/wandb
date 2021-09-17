"""
pytorch profiler
"""
import wandb

PYTORCH_PROFILER_MODULE = "torch.profiler"


def trace():
    torch_profiler = wandb.util.get_module(PYTORCH_PROFILER_MODULE)
    try:
        logdir = wandb.run.dir
    except AttributeError:
        raise Exception(
            "Please call wandb.init() before wandb.profiler.trace()"
        ) from None

    return torch_profiler.tensorboard_trace_handler(
        logdir, worker_name=None, use_gzip=False
    )


def test_file_upload_good(mocked_run, publish_util, mock_server):
    def begin_fn(interface):
        with open(os.path.join(mocked_run.dir, "test.txt"), "w") as f:
            f.write("TEST TEST")

    files = [dict(files_dict=dict(files=[("test.txt", "now")]))]
    ctx_util = publish_util(files=files, begin_cb=begin_fn)
    assert "test.txt" in ctx_util.file_names
