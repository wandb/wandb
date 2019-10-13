# TensorBoard

### TensorBoard and TensorboardX

W&B supports patching TensorBoard or [TensorboardX](https://github.com/lanpa/tensorboardX) to automatically log all summaries.

```text
import wandb
wandb.init(sync_tensorboard=True)
```

Under the hood the patch tries to guess which version of TensorBoard to patch. We support TensorBoard with all versions of TensorFlow. If you're using TensorBoard with another framework W&B supports tensorboard &gt; 1.14 with PyTorch as well as TensorboardX.

### Custom Metrics

If you need to log additional custom metrics that aren't being logged to TensorBoard, you can call `wandb.log` in your code with the same step argument that TensorBoard is using: i.e. `wandb.log({"custom": 0.8}, step=global_step)`

### Advanced Configuration

If you want more control over how TensorBoard is patched you can call `wandb.tensorboard.patch` instead of passing `sync_tensorboard=True` to init. You can pass `tensorboardX=False` to this method to ensure vanilla TensorBoard is patched, if you're using tensorboard &gt; 1.14 with PyTorch you can pass `pytorch=True` to ensure it's patched. Both of these options are have smart defaults depending on what versions of these libraries have been imported.

By default we also sync the tfevents files and any \*.pbtxt files. This enables us to launch a TensorBoard instance on your behalf. You will see a [TensorBoard tab](https://www.wandb.com/articles/hosted-tensorboard) on the run page. This behavior can be disabled by ~~~~passing `save=False` to `wandb.tensorboard.patch`

```text
import wandb
wandb.init()
wandb.tensorboard.patch(save=False, tensorboardX=True)
```

### Syncing Previous TensorBoard Runs

If you have existing experiments you would like to import into wandb, you can run `wandb sync log_dir` where log\_dir is a local directory containing the tfevents files.

