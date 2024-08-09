"""Weights & Biases Models: use wandb to train and productionize models.

Train and fine-tune models, manage models from experimentation to production.

For guides and examples, see https://docs.wandb.ai.

For scripts and interactive notebooks, see https://github.com/wandb/examples.

For reference documentation, see https://docs.wandb.com/ref/python.
"""

import os
from typing import Any, Dict, List, Optional, Sequence, Union

from wandb.sdk import Settings
from wandb.sdk.interface.interface import PolicyName
from wandb.sdk.lib.paths import StrPath
from wandb.sdk.wandb_run import Run
from wandb.sdk.wandb_setup import _WandbSetup

__version__: str = "0.17.7.dev1"

def setup(
    settings: Optional[Settings] = None,
) -> Optional[_WandbSetup]:
    """Set up a wandb session.

    Note: This sets up a process-local singleton object.
    (Forked processes will get a new copy of the object)
    """
    ...

def init(
    job_type: Optional[str] = None,
    dir: Optional[StrPath] = None,
    config: Union[Dict, str, None] = None,
    project: Optional[str] = None,
    entity: Optional[str] = None,
    reinit: Optional[bool] = None,
    tags: Optional[Sequence] = None,
    group: Optional[str] = None,
    name: Optional[str] = None,
    notes: Optional[str] = None,
    magic: Optional[Union[dict, str, bool]] = None,
    config_exclude_keys: Optional[List[str]] = None,
    config_include_keys: Optional[List[str]] = None,
    anonymous: Optional[str] = None,
    mode: Optional[str] = None,
    allow_val_change: Optional[bool] = None,
    resume: Optional[Union[bool, str]] = None,
    force: Optional[bool] = None,
    tensorboard: Optional[bool] = None,  # alias for sync_tensorboard
    sync_tensorboard: Optional[bool] = None,
    monitor_gym: Optional[bool] = None,
    save_code: Optional[bool] = None,
    id: Optional[str] = None,
    fork_from: Optional[str] = None,
    resume_from: Optional[str] = None,
    settings: Union[Settings, Dict[str, Any], None] = None,
) -> Run:
    r"""Start a new run to track and log to W&B.

    In an ML training pipeline, you could add `wandb.init()`
    to the beginning of your training script as well as your evaluation
    script, and each piece would be tracked as a run in W&B.

    `wandb.init()` spawns a new background process to log data to a run, and it
    also syncs data to wandb.ai by default, so you can see live visualizations.

    Call `wandb.init()` to start a run before logging data with `wandb.log()`:
    <!--yeadoc-test:init-method-log-->
    ```python
    import wandb

    wandb.init()
    # ... calculate metrics, generate media
    wandb.log({"accuracy": 0.9})
    ```

    `wandb.init()` returns a run object, and you can also access the run object
    via `wandb.run`:
    <!--yeadoc-test:init-and-assert-global-->
    ```python
    import wandb

    run = wandb.init()

    assert run is wandb.run
    ```

    At the end of your script, we will automatically call `wandb.finish` to
    finalize and cleanup the run. However, if you call `wandb.init` from a
    child process, you must explicitly call `wandb.finish` at the end of the
    child process.

    For more on using `wandb.init()`, including detailed examples, check out our
    [guide and FAQs](https://docs.wandb.ai/guides/track/launch).

    Arguments:
        project: (str, optional) The name of the project where you're sending
            the new run. If the project is not specified, we will try to infer
            the project name from git root or the current program file. If we
            can't infer the project name, we will default to `"uncategorized"`.
        entity: (str, optional) An entity is a username or team name where
            you're sending runs. This entity must exist before you can send runs
            there, so make sure to create your account or team in the UI before
            starting to log runs.
            If you don't specify an entity, the run will be sent to your default
            entity. Change your default entity
            in [your settings](https://wandb.ai/settings) under "default location
            to create new projects".
        config: (dict, argparse, absl.flags, str, optional)
            This sets `wandb.config`, a dictionary-like object for saving inputs
            to your job, like hyperparameters for a model or settings for a data
            preprocessing job. The config will show up in a table in the UI that
            you can use to group, filter, and sort runs. Keys should not contain
            `.` in their names, and values should be under 10 MB.
            If dict, argparse or absl.flags: will load the key value pairs into
                the `wandb.config` object.
            If str: will look for a yaml file by that name, and load config from
                that file into the `wandb.config` object.
        save_code: (bool, optional) Turn this on to save the main script or
            notebook to W&B. This is valuable for improving experiment
            reproducibility and to diff code across experiments in the UI. By
            default this is off, but you can flip the default behavior to on
            in [your settings page](https://wandb.ai/settings).
        group: (str, optional) Specify a group to organize individual runs into
            a larger experiment. For example, you might be doing cross
            validation, or you might have multiple jobs that train and evaluate
            a model against different test sets. Group gives you a way to
            organize runs together into a larger whole, and you can toggle this
            on and off in the UI. For more details, see our
            [guide to grouping runs](https://docs.wandb.com/guides/runs/grouping).
        job_type: (str, optional) Specify the type of run, which is useful when
            you're grouping runs together into larger experiments using group.
            For example, you might have multiple jobs in a group, with job types
            like train and eval. Setting this makes it easy to filter and group
            similar runs together in the UI so you can compare apples to apples.
        tags: (list, optional) A list of strings, which will populate the list
            of tags on this run in the UI. Tags are useful for organizing runs
            together, or applying temporary labels like "baseline" or
            "production". It's easy to add and remove tags in the UI, or filter
            down to just runs with a specific tag.
            If you are resuming a run, its tags will be overwritten by the tags
            you pass to `wandb.init()`. If you want to add tags to a resumed run
            without overwriting its existing tags, use `run.tags += ["new_tag"]`
            after `wandb.init()`.
        name: (str, optional) A short display name for this run, which is how
            you'll identify this run in the UI. By default, we generate a random
            two-word name that lets you easily cross-reference runs from the
            table to charts. Keeping these run names short makes the chart
            legends and tables easier to read. If you're looking for a place to
            save your hyperparameters, we recommend saving those in config.
        notes: (str, optional) A longer description of the run, like a `-m` commit
            message in git. This helps you remember what you were doing when you
            ran this run.
        dir: (str or pathlib.Path, optional) An absolute path to a directory where
            metadata will be stored. When you call `download()` on an artifact,
            this is the directory where downloaded files will be saved. By default,
            this is the `./wandb` directory.
        resume: (bool, str, optional) Sets the resuming behavior. Options:
            `"allow"`, `"must"`, `"never"`, `"auto"` or `None`. Defaults to `None`.
            Cases:
            - `None` (default): If the new run has the same ID as a previous run,
                this run overwrites that data.
            - `"auto"` (or `True`): if the previous run on this machine crashed,
                automatically resume it. Otherwise, start a new run.
            - `"allow"`: if id is set with `init(id="UNIQUE_ID")` or
                `WANDB_RUN_ID="UNIQUE_ID"` and it is identical to a previous run,
                wandb will automatically resume the run with that id. Otherwise,
                wandb will start a new run.
            - `"never"`: if id is set with `init(id="UNIQUE_ID")` or
                `WANDB_RUN_ID="UNIQUE_ID"` and it is identical to a previous run,
                wandb will crash.
            - `"must"`: if id is set with `init(id="UNIQUE_ID")` or
                `WANDB_RUN_ID="UNIQUE_ID"` and it is identical to a previous run,
                wandb will automatically resume the run with the id. Otherwise,
                wandb will crash.
            See [our guide to resuming runs](https://docs.wandb.com/guides/runs/resuming)
            for more.
        reinit: (bool, optional) Allow multiple `wandb.init()` calls in the same
            process. (default: `False`)
        magic: (bool, dict, or str, optional) The bool controls whether we try to
            auto-instrument your script, capturing basic details of your run
            without you having to add more wandb code. (default: `False`)
            You can also pass a dict, json string, or yaml filename.
        config_exclude_keys: (list, optional) string keys to exclude from
            `wandb.config`.
        config_include_keys: (list, optional) string keys to include in
            `wandb.config`.
        anonymous: (str, optional) Controls anonymous data logging. Options:
            - `"never"` (default): requires you to link your W&B account before
                tracking the run, so you don't accidentally create an anonymous
                run.
            - `"allow"`: lets a logged-in user track runs with their account, but
                lets someone who is running the script without a W&B account see
                the charts in the UI.
            - `"must"`: sends the run to an anonymous account instead of to a
                signed-up user account.
        mode: (str, optional) Can be `"online"`, `"offline"` or `"disabled"`. Defaults to
            online.
        allow_val_change: (bool, optional) Whether to allow config values to
            change after setting the keys once. By default, we throw an exception
            if a config value is overwritten. If you want to track something
            like a varying learning rate at multiple times during training, use
            `wandb.log()` instead. (default: `False` in scripts, `True` in Jupyter)
        force: (bool, optional) If `True`, this crashes the script if a user isn't
            logged in to W&B. If `False`, this will let the script run in offline
            mode if a user isn't logged in to W&B. (default: `False`)
        sync_tensorboard: (bool, optional) Synchronize wandb logs from tensorboard or
            tensorboardX and save the relevant events file. (default: `False`)
        monitor_gym: (bool, optional) Automatically log videos of environment when
            using OpenAI Gym. (default: `False`)
            See [our guide to this integration](https://docs.wandb.com/guides/integrations/openai-gym).
        id: (str, optional) A unique ID for this run, used for resuming. It must
            be unique in the project, and if you delete a run you can't reuse
            the ID. Use the `name` field for a short descriptive name, or `config`
            for saving hyperparameters to compare across runs. The ID cannot
            contain the following special characters: `/\#?%:`.
            See [our guide to resuming runs](https://docs.wandb.com/guides/runs/resuming).
        fork_from: (str, optional) A string with the format {run_id}?_step={step} describing
            a moment in a previous run to fork a new run from. Creates a new run that picks up
            logging history from the specified run at the specified moment. The target run must
            be in the current project. Example: `fork_from="my-run-id?_step=1234"`.

    Examples:
    ### Set where the run is logged

    You can change where the run is logged, just like changing
    the organization, repository, and branch in git:
    ```python
    import wandb

    user = "geoff"
    project = "capsules"
    display_name = "experiment-2021-10-31"

    wandb.init(entity=user, project=project, name=display_name)
    ```

    ### Add metadata about the run to the config

    Pass a dictionary-style object as the `config` keyword argument to add
    metadata, like hyperparameters, to your run.
    <!--yeadoc-test:init-set-config-->
    ```python
    import wandb

    config = {"lr": 3e-4, "batch_size": 32}
    config.update({"architecture": "resnet", "depth": 34})
    wandb.init(config=config)
    ```

    Raises:
        Error: if some unknown or internal error happened during the run initialization.
        AuthenticationError: if the user failed to provide valid credentials.
        CommError: if there was a problem communicating with the WandB server.
        UsageError: if the user provided invalid arguments.
        KeyboardInterrupt: if user interrupts the run.

    Returns:
    A `Run` object.
    """
    ...

def log(
    data: Dict[str, Any],
    step: Optional[int] = None,
    commit: Optional[bool] = None,
    sync: Optional[bool] = None,
) -> None:
    """Log a dictionary of data to the current run's history.

    Use `wandb.log` to log data from runs, such as scalars, images, video,
    histograms, plots, and tables.

    See our [guides to logging](https://docs.wandb.ai/guides/track/log) for
    live examples, code snippets, best practices, and more.

    The most basic usage is `wandb.log({"train-loss": 0.5, "accuracy": 0.9})`.
    This will save the loss and accuracy to the run's history and update
    the summary values for these metrics.

    Visualize logged data in the workspace at [wandb.ai](https://wandb.ai),
    or locally on a [self-hosted instance](https://docs.wandb.ai/guides/hosting)
    of the W&B app, or export data to visualize and explore locally, e.g. in
    Jupyter notebooks, with [our API](https://docs.wandb.ai/guides/track/public-api-guide).

    In the UI, summary values show up in the run table to compare single values across runs.
    Summary values can also be set directly with `wandb.run.summary["key"] = value`.

    Logged values don't have to be scalars. Logging any wandb object is supported.
    For example `wandb.log({"example": wandb.Image("myimage.jpg")})` will log an
    example image which will be displayed nicely in the W&B UI.
    See the [reference documentation](https://docs.wandb.com/ref/python/data-types)
    for all of the different supported types or check out our
    [guides to logging](https://docs.wandb.ai/guides/track/log) for examples,
    from 3D molecular structures and segmentation masks to PR curves and histograms.
    `wandb.Table`s can be used to logged structured data. See our
    [guide to logging tables](https://docs.wandb.ai/guides/data-vis/log-tables)
    for details.

    Logging nested metrics is encouraged and is supported in the W&B UI.
    If you log with a nested dictionary like `wandb.log({"train":
    {"acc": 0.9}, "val": {"acc": 0.8}})`, the metrics will be organized into
    `train` and `val` sections in the W&B UI.

    wandb keeps track of a global step, which by default increments with each
    call to `wandb.log`, so logging related metrics together is encouraged.
    If it's inconvenient to log related metrics together
    calling `wandb.log({"train-loss": 0.5}, commit=False)` and then
    `wandb.log({"accuracy": 0.9})` is equivalent to calling
    `wandb.log({"train-loss": 0.5, "accuracy": 0.9})`.

    `wandb.log` is not intended to be called more than a few times per second.
    If you want to log more frequently than that it's better to aggregate
    the data on the client side or you may get degraded performance.

    Arguments:
        data: (dict, optional) A dict of serializable python objects i.e `str`,
            `ints`, `floats`, `Tensors`, `dicts`, or any of the `wandb.data_types`.
        commit: (boolean, optional) Save the metrics dict to the wandb server
            and increment the step.  If false `wandb.log` just updates the current
            metrics dict with the data argument and metrics won't be saved until
            `wandb.log` is called with `commit=True`.
        step: (integer, optional) The global step in processing. This persists
            any non-committed earlier steps but defaults to not committing the
            specified step.
        sync: (boolean, True) This argument is deprecated and currently doesn't
            change the behaviour of `wandb.log`.

    Examples:
        For more and more detailed examples, see
        [our guides to logging](https://docs.wandb.com/guides/track/log).

        ### Basic usage
        <!--yeadoc-test:init-and-log-basic-->
        ```python
        import wandb

        run = wandb.init()
        run.log({"accuracy": 0.9, "epoch": 5})
        ```

        ### Incremental logging
        <!--yeadoc-test:init-and-log-incremental-->
        ```python
        import wandb

        run = wandb.init()
        run.log({"loss": 0.2}, commit=False)
        # Somewhere else when I'm ready to report this step:
        run.log({"accuracy": 0.8})
        ```

        ### Histogram
        <!--yeadoc-test:init-and-log-histogram-->
        ```python
        import numpy as np
        import wandb

        # sample gradients at random from normal distribution
        gradients = np.random.randn(100, 100)
        run = wandb.init()
        run.log({"gradients": wandb.Histogram(gradients)})
        ```

        ### Image from numpy
        <!--yeadoc-test:init-and-log-image-numpy-->
        ```python
        import numpy as np
        import wandb

        run = wandb.init()
        examples = []
        for i in range(3):
            pixels = np.random.randint(low=0, high=256, size=(100, 100, 3))
            image = wandb.Image(pixels, caption=f"random field {i}")
            examples.append(image)
        run.log({"examples": examples})
        ```

        ### Image from PIL
        <!--yeadoc-test:init-and-log-image-pillow-->
        ```python
        import numpy as np
        from PIL import Image as PILImage
        import wandb

        run = wandb.init()
        examples = []
        for i in range(3):
            pixels = np.random.randint(low=0, high=256, size=(100, 100, 3), dtype=np.uint8)
            pil_image = PILImage.fromarray(pixels, mode="RGB")
            image = wandb.Image(pil_image, caption=f"random field {i}")
            examples.append(image)
        run.log({"examples": examples})
        ```

        ### Video from numpy
        <!--yeadoc-test:init-and-log-video-numpy-->
        ```python
        import numpy as np
        import wandb

        run = wandb.init()
        # axes are (time, channel, height, width)
        frames = np.random.randint(low=0, high=256, size=(10, 3, 100, 100), dtype=np.uint8)
        run.log({"video": wandb.Video(frames, fps=4)})
        ```

        ### Matplotlib Plot
        <!--yeadoc-test:init-and-log-matplotlib-->
        ```python
        from matplotlib import pyplot as plt
        import numpy as np
        import wandb

        run = wandb.init()
        fig, ax = plt.subplots()
        x = np.linspace(0, 10)
        y = x * x
        ax.plot(x, y)  # plot y = x^2
        run.log({"chart": fig})
        ```

        ### PR Curve
        ```python
        import wandb

        run = wandb.init()
        run.log({"pr": wandb.plot.pr_curve(y_test, y_probas, labels)})
        ```

        ### 3D Object
        ```python
        import wandb

        run = wandb.init()
        run.log(
            {
                "generated_samples": [
                    wandb.Object3D(open("sample.obj")),
                    wandb.Object3D(open("sample.gltf")),
                    wandb.Object3D(open("sample.glb")),
                ]
            }
        )
        ```

    Raises:
        wandb.Error: if called before `wandb.init`
    ValueError: if invalid data is passed
    """
    ...

def save(
    glob_str: Optional[Union[str, os.PathLike]] = None,
    base_path: Optional[Union[str, os.PathLike]] = None,
    policy: PolicyName = "live",
) -> Union[bool, List[str]]:
    """Sync one or more files to W&B.

    Relative paths are relative to the current working directory.

    A Unix glob, such as "myfiles/*", is expanded at the time `save` is
    called regardless of the `policy`. In particular, new files are not
    picked up automatically.

    A `base_path` may be provided to control the directory structure of
    uploaded files. It should be a prefix of `glob_str`, and the directory
    structure beneath it is preserved. It's best understood through
    examples:

    ```
    wandb.save("these/are/myfiles/*")
    # => Saves files in a "these/are/myfiles/" folder in the run.

    wandb.save("these/are/myfiles/*", base_path="these")
    # => Saves files in an "are/myfiles/" folder in the run.

    wandb.save("/User/username/Documents/run123/*.txt")
    # => Saves files in a "run123/" folder in the run. See note below.

    wandb.save("/User/username/Documents/run123/*.txt", base_path="/User")
    # => Saves files in a "username/Documents/run123/" folder in the run.

    wandb.save("files/*/saveme.txt")
    # => Saves each "saveme.txt" file in an appropriate subdirectory
    #    of "files/".
    ```

    Note: when given an absolute path or glob and no `base_path`, one
    directory level is preserved as in the example above.

    Arguments:
        glob_str: A relative or absolute path or Unix glob.
        base_path: A path to use to infer a directory structure; see examples.
        policy: One of `live`, `now`, or `end`.
            * live: upload the file as it changes, overwriting the previous version
            * now: upload the file once now
            * end: upload file when the run ends

    Returns:
        Paths to the symlinks created for the matched files.

    For historical reasons, this may return a boolean in legacy code.
    """
    ...
