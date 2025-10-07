"""Use wandb to track machine learning work.

Train and fine-tune models, manage models from experimentation to production.

For guides and examples, see https://docs.wandb.ai.

For scripts and interactive notebooks, see https://github.com/wandb/examples.

For reference documentation, see https://docs.wandb.com/ref/python.
"""

from __future__ import annotations

__all__ = (
    "__version__",  # doc:exclude
    "init",
    "finish",
    "setup",
    "login",
    "save",  # doc:exclude
    "sweep",
    "controller",
    "agent",
    "config",  # doc:exclude
    "log",  # doc:exclude
    "summary",  # doc:exclude
    "Api",
    "Graph",  # doc:exclude
    "Image",
    "Plotly",
    "Video",
    "Audio",
    "Table",
    "Html",
    "box3d",
    "Object3D",
    "Molecule",
    "Histogram",
    "ArtifactTTL",  # doc:exclude
    "log_artifact",  # doc:exclude
    "use_artifact",  # doc:exclude
    "log_model",  # doc:exclude
    "use_model",  # doc:exclude
    "link_model",  # doc:exclude
    "define_metric",  # doc:exclude
    "Error",  # doc:exclude
    "termsetup",  # doc:exclude
    "termlog",  # doc:exclude
    "termerror",  # doc:exclude
    "termwarn",  # doc:exclude
    "Artifact",
    "Settings",
    "teardown",
    "watch",  # doc:exclude
    "unwatch",  # doc:exclude
    "plot",  # doc:exclude
    "plot_table",
    "restore",
    "Run",
)

import os
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    Dict,
    Iterable,
    List,
    Literal,
    Optional,
    Sequence,
    TextIO,
    Union,
)

import wandb.plot as plot
from wandb.analytics import Sentry
from wandb.apis import InternalApi
from wandb.apis import PublicApi as Api
from wandb.data_types import (
    Audio,
    Graph,
    Histogram,
    Html,
    Image,
    Molecule,
    Object3D,
    Plotly,
    Table,
    Video,
    box3d,
)
from wandb.errors import Error
from wandb.errors.term import termerror, termlog, termsetup, termwarn
from wandb.sdk import Artifact, Settings, wandb_config, wandb_metric, wandb_summary
from wandb.sdk.artifacts.artifact_ttl import ArtifactTTL
from wandb.sdk.interface.interface import PolicyName
from wandb.sdk.lib.paths import FilePathStr, StrPath
from wandb.sdk.wandb_run import Run
from wandb.sdk.wandb_setup import _WandbSetup
from wandb.wandb_controller import _WandbController

if TYPE_CHECKING:
    import torch  # type: ignore [import-not-found]

    import wandb
    from wandb.plot import CustomChart

__version__: str = "0.22.2"

run: Run | None
config: wandb_config.Config
summary: wandb_summary.Summary

# private attributes
_sentry: Sentry
api: InternalApi
patched: Dict[str, List[Callable]]

def require(
    requirement: str | Iterable[str] | None = None,
    experiment: str | Iterable[str] | None = None,
) -> None:
    """Indicate which experimental features are used by the script.

    This should be called before any other `wandb` functions, ideally right
    after importing `wandb`.

    Args:
        requirement: The name of a feature to require or an iterable of
            feature names.
        experiment: An alias for `requirement`.

    Raises:
        wandb.errors.UnsupportedError: If a feature name is unknown.
    """
    ...

def setup(settings: Settings | None = None) -> _WandbSetup:
    """Prepares W&B for use in the current process and its children.

    You can usually ignore this as it is implicitly called by `wandb.init()`.

    When using wandb in multiple processes, calling `wandb.setup()`
    in the parent process before starting child processes may improve
    performance and resource utilization.

    Note that `wandb.setup()` modifies `os.environ`, and it is important
    that child processes inherit the modified environment variables.

    See also `wandb.teardown()`.

    Args:
        settings: Configuration settings to apply globally. These can be
            overridden by subsequent `wandb.init()` calls.

    Example:
    ```python
    import multiprocessing

    import wandb

    def run_experiment(params):
        with wandb.init(config=params):
            # Run experiment
            pass

    if __name__ == "__main__":
        # Start backend and set global config
        wandb.setup(settings={"project": "my_project"})

        # Define experiment parameters
        experiment_params = [
            {"learning_rate": 0.01, "epochs": 10},
            {"learning_rate": 0.001, "epochs": 20},
        ]

        # Start multiple processes, each running a separate experiment
        processes = []
        for params in experiment_params:
            p = multiprocessing.Process(target=run_experiment, args=(params,))
            p.start()
            processes.append(p)

        # Wait for all processes to complete
        for p in processes:
            p.join()

        # Optional: Explicitly shut down the backend
        wandb.teardown()
    ```
    """
    ...

def teardown(exit_code: int | None = None) -> None:
    """Waits for W&B to finish and frees resources.

    Completes any runs that were not explicitly finished
    using `run.finish()` and waits for all data to be uploaded.

    It is recommended to call this at the end of a session
    that used `wandb.setup()`. It is invoked automatically
    in an `atexit` hook, but this is not reliable in certain setups
    such as when using Python's `multiprocessing` module.
    """
    ...

def init(
    entity: str | None = None,
    project: str | None = None,
    dir: StrPath | None = None,
    id: str | None = None,
    name: str | None = None,
    notes: str | None = None,
    tags: Sequence[str] | None = None,
    config: dict[str, Any] | str | None = None,
    config_exclude_keys: list[str] | None = None,
    config_include_keys: list[str] | None = None,
    allow_val_change: bool | None = None,
    group: str | None = None,
    job_type: str | None = None,
    mode: Literal["online", "offline", "disabled", "shared"] | None = None,
    force: bool | None = None,
    anonymous: Literal["never", "allow", "must"] | None = None,
    reinit: (
        bool
        | Literal[
            None,
            "default",
            "return_previous",
            "finish_previous",
            "create_new",
        ]
    ) = None,
    resume: bool | Literal["allow", "never", "must", "auto"] | None = None,
    resume_from: str | None = None,
    fork_from: str | None = None,
    save_code: bool | None = None,
    tensorboard: bool | None = None,
    sync_tensorboard: bool | None = None,
    monitor_gym: bool | None = None,
    settings: Settings | dict[str, Any] | None = None,
) -> Run:
    r"""Start a new run to track and log to W&B.

    In an ML training pipeline, you could add `wandb.init()` to the beginning of
    your training script as well as your evaluation script, and each piece would
    be tracked as a run in W&B.

    `wandb.init()` spawns a new background process to log data to a run, and it
    also syncs data to https://wandb.ai by default, so you can see your results
    in real-time. When you're done logging data, call `wandb.Run.finish()` to end the run.
    If you don't call `run.finish()`, the run will end when your script exits.

    Run IDs must not contain any of the following special characters `/ \ # ? % :`

    Args:
        entity: The username or team name the runs are logged to.
            The entity must already exist, so ensure you create your account
            or team in the UI before starting to log runs. If not specified, the
            run will default your default entity. To change the default entity,
            go to your settings and update the
            "Default location to create new projects" under "Default team".
        project: The name of the project under which this run will be logged.
            If not specified, we use a heuristic to infer the project name based
            on the system, such as checking the git root or the current program
            file. If we can't infer the project name, the project will default to
            `"uncategorized"`.
        dir: The absolute path to the directory where experiment logs and
            metadata files are stored. If not specified, this defaults
            to the `./wandb` directory. Note that this does not affect the
            location where artifacts are stored when calling `download()`.
        id: A unique identifier for this run, used for resuming. It must be unique
            within the project and cannot be reused once a run is deleted. For
            a short descriptive name, use the `name` field,
            or for saving hyperparameters to compare across runs, use `config`.
        name: A short display name for this run, which appears in the UI to help
            you identify it. By default, we generate a random two-word name
            allowing easy cross-reference runs from table to charts. Keeping these
            run names brief enhances readability in chart legends and tables. For
            saving hyperparameters, we recommend using the `config` field.
        notes: A detailed description of the run, similar to a commit message in
            Git. Use this argument to capture any context or details that may
            help you recall the purpose or setup of this run in the future.
        tags: A list of tags to label this run in the UI. Tags are helpful for
            organizing runs or adding temporary identifiers like "baseline" or
            "production." You can easily add, remove tags, or filter by tags in
            the UI.
            If resuming a run, the tags provided here will replace any existing
            tags. To add tags to a resumed run without overwriting the current
            tags, use `run.tags += ("new_tag",)` after calling `run = wandb.init()`.
        config: Sets `wandb.config`, a dictionary-like object for storing input
            parameters to your run, such as model hyperparameters or data
            preprocessing settings.
            The config appears in the UI in an overview page, allowing you to
            group, filter, and sort runs based on these parameters.
            Keys should not contain periods (`.`), and values should be
            smaller than 10 MB.
            If a dictionary, `argparse.Namespace`, or `absl.flags.FLAGS` is
            provided, the key-value pairs will be loaded directly into
            `wandb.config`.
            If a string is provided, it is interpreted as a path to a YAML file,
            from which configuration values will be loaded into `wandb.config`.
        config_exclude_keys: A list of specific keys to exclude from `wandb.config`.
        config_include_keys: A list of specific keys to include in `wandb.config`.
        allow_val_change: Controls whether config values can be modified after their
            initial set. By default, an exception is raised if a config value is
            overwritten. For tracking variables that change during training, such as
            a learning rate, consider using `wandb.log()` instead. By default, this
            is `False` in scripts and `True` in Notebook environments.
        group: Specify a group name to organize individual runs as part of a larger
            experiment. This is useful for cases like cross-validation or running
            multiple jobs that train and evaluate a model on different test sets.
            Grouping allows you to manage related runs collectively in the UI,
            making it easy to toggle and review results as a unified experiment.
        job_type: Specify the type of run, especially helpful when organizing runs
            within a group as part of a larger experiment. For example, in a group,
            you might label runs with job types such as "train" and "eval".
            Defining job types enables you to easily filter and group similar runs
            in the UI, facilitating direct comparisons.
        mode: Specifies how run data is managed, with the following options:
        - `"online"` (default): Enables live syncing with W&B when a network
            connection is available, with real-time updates to visualizations.
        - `"offline"`: Suitable for air-gapped or offline environments; data
            is saved locally and can be synced later. Ensure the run folder
            is preserved to enable future syncing.
        - `"disabled"`: Disables all W&B functionality, making the run’s methods
            no-ops. Typically used in testing to bypass W&B operations.
        - `"shared"`: (This is an experimental feature). Allows multiple processes,
            possibly on different machines, to simultaneously log to the same run.
            In this approach you use a primary node and one or more worker nodes
            to log data to the same run. Within the primary node you
            initialize a run. For each worker node, initialize a run
            using the run ID used by the primary node.
        force: Determines if a W&B login is required to run the script. If `True`,
            the user must be logged in to W&B; otherwise, the script will not
            proceed. If `False` (default), the script can proceed without a login,
            switching to offline mode if the user is not logged in.
        anonymous: Specifies the level of control over anonymous data logging.
            Available options are:
        - `"never"` (default): Requires you to link your W&B account before
            tracking the run. This prevents unintentional creation of anonymous
            runs by ensuring each run is associated with an account.
        - `"allow"`: Enables a logged-in user to track runs with their account,
            but also allows someone running the script without a W&B account
            to view the charts and data in the UI.
        - `"must"`: Forces the run to be logged to an anonymous account, even
            if the user is logged in.
        reinit: Shorthand for the "reinit" setting. Determines the behavior of
            `wandb.init()` when a run is active.
        resume: Controls the behavior when resuming a run with the specified `id`.
            Available options are:
        - `"allow"`: If a run with the specified `id` exists, it will resume
            from the last step; otherwise, a new run will be created.
        - `"never"`: If a run with the specified `id` exists, an error will
            be raised. If no such run is found, a new run will be created.
        - `"must"`: If a run with the specified `id` exists, it will resume
            from the last step. If no run is found, an error will be raised.
        - `"auto"`: Automatically resumes the previous run if it crashed on
            this machine; otherwise, starts a new run.
        - `True`: Deprecated. Use `"auto"` instead.
        - `False`: Deprecated. Use the default behavior (leaving `resume`
            unset) to always start a new run.
            If `resume` is set, `fork_from` and `resume_from` cannot be
            used. When `resume` is unset, the system will always start a new run.
        resume_from: Specifies a moment in a previous run to resume a run from,
            using the format `{run_id}?_step={step}`. This allows users to truncate
            the history logged to a run at an intermediate step and resume logging
            from that step. The target run must be in the same project.
            If an `id` argument is also provided, the `resume_from` argument will
            take precedence.
            `resume`, `resume_from` and `fork_from` cannot be used together, only
            one of them can be used at a time.
            Note that this feature is in beta and may change in the future.
        fork_from: Specifies a point in a previous run from which to fork a new
            run, using the format `{id}?_step={step}`. This creates a new run that
            resumes logging from the specified step in the target run’s history.
            The target run must be part of the current project.
            If an `id` argument is also provided, it must be different from the
            `fork_from` argument, an error will be raised if they are the same.
            `resume`, `resume_from` and `fork_from` cannot be used together, only
            one of them can be used at a time.
            Note that this feature is in beta and may change in the future.
        save_code: Enables saving the main script or notebook to W&B, aiding in
            experiment reproducibility and allowing code comparisons across runs in
            the UI. By default, this is disabled, but you can change the default to
            enable on your settings page.
        tensorboard: Deprecated. Use `sync_tensorboard` instead.
        sync_tensorboard: Enables automatic syncing of W&B logs from TensorBoard
            or TensorBoardX, saving relevant event files for viewing in
            the W&B UI.
        monitor_gym: Enables automatic logging of videos of the environment when
            using OpenAI Gym.
        settings: Specifies a dictionary or `wandb.Settings` object with advanced
            settings for the run.

    Returns:
        A `Run` object.

    Raises:
        Error: If some unknown or internal error happened during the run
            initialization.
        AuthenticationError: If the user failed to provide valid credentials.
        CommError: If there was a problem communicating with the WandB server.
        UsageError: If the user provided invalid arguments.
        KeyboardInterrupt: If user interrupts the run.

    Examples:
    `wandb.init()` returns a `Run` object. Use the run object to log data,
    save artifacts, and manage the run lifecycle.

    ```python
    import wandb

    config = {"lr": 0.01, "batch_size": 32}
    with wandb.init(config=config) as run:
        # Log accuracy and loss to the run
        acc = 0.95  # Example accuracy
        loss = 0.05  # Example loss
        run.log({"accuracy": acc, "loss": loss})
    ```
    """
    ...

def finish(
    exit_code: int | None = None,
    quiet: bool | None = None,
) -> None:
    """Finish a run and upload any remaining data.

    Marks the completion of a W&B run and ensures all data is synced to the server.
    The run's final state is determined by its exit conditions and sync status.

    Run States:
    - Running: Active run that is logging data and/or sending heartbeats.
    - Crashed: Run that stopped sending heartbeats unexpectedly.
    - Finished: Run completed successfully (`exit_code=0`) with all data synced.
    - Failed: Run completed with errors (`exit_code!=0`).

    Args:
        exit_code: Integer indicating the run's exit status. Use 0 for success,
            any other value marks the run as failed.
        quiet: Deprecated. Configure logging verbosity using `wandb.Settings(quiet=...)`.
    """
    ...

def login(
    anonymous: Optional[Literal["must", "allow", "never"]] = None,
    key: Optional[str] = None,
    relogin: Optional[bool] = None,
    host: Optional[str] = None,
    force: Optional[bool] = None,
    timeout: Optional[int] = None,
    verify: bool = False,
    referrer: Optional[str] = None,
) -> bool:
    """Set up W&B login credentials.

    By default, this will only store credentials locally without
    verifying them with the W&B server. To verify credentials, pass
    `verify=True`.

    Args:
        anonymous: Set to "must", "allow", or "never".
            If set to "must", always log a user in anonymously. If set to
            "allow", only create an anonymous user if the user
            isn't already logged in. If set to "never", never log a
            user anonymously. Default set to "never". Defaults to `None`.
        key: The API key to use.
        relogin: If true, will re-prompt for API key.
        host: The host to connect to.
        force: If true, will force a relogin.
        timeout: Number of seconds to wait for user input.
        verify: Verify the credentials with the W&B server.
        referrer: The referrer to use in the URL login request.


    Returns:
        bool: If `key` is configured.

    Raises:
        AuthenticationError: If `api_key` fails verification with the server.
        UsageError: If `api_key` cannot be configured and no tty.
    """
    ...

def log(
    data: dict[str, Any],
    step: int | None = None,
    commit: bool | None = None,
) -> None:
    """Upload run data.

    Use `log` to log data from runs, such as scalars, images, video,
    histograms, plots, and tables. See [Log objects and media](https://docs.wandb.ai/guides/track/log) for
    code snippets, best practices, and more.

    Basic usage:

    ```python
    import wandb

    with wandb.init() as run:
        run.log({"train-loss": 0.5, "accuracy": 0.9})
    ```

    The previous code snippet saves the loss and accuracy to the run's
    history and updates the summary values for these metrics.

    Visualize logged data in a workspace at [wandb.ai](https://wandb.ai),
    or locally on a [self-hosted instance](https://docs.wandb.ai/guides/hosting)
    of the W&B app, or export data to visualize and explore locally, such as in a
    Jupyter notebook, with the [Public API](https://docs.wandb.ai/guides/track/public-api-guide).

    Logged values don't have to be scalars. You can log any
    [W&B supported Data Type](https://docs.wandb.ai/ref/python/data-types/)
    such as images, audio, video, and more. For example, you can use
    `wandb.Table` to log structured data. See
    [Log tables, visualize and query data](https://docs.wandb.ai/guides/models/tables/tables-walkthrough)
    tutorial for more details.

    W&B organizes metrics with a forward slash (`/`) in their name
    into sections named using the text before the final slash. For example,
    the following results in two sections named "train" and "validate":

    ```python
    with wandb.init() as run:
        # Log metrics in the "train" section.
        run.log(
            {
                "train/accuracy": 0.9,
                "train/loss": 30,
                "validate/accuracy": 0.8,
                "validate/loss": 20,
            }
        )
    ```

    Only one level of nesting is supported; `run.log({"a/b/c": 1})`
    produces a section named "a/b".

    `run.log()` is not intended to be called more than a few times per second.
    For optimal performance, limit your logging to once every N iterations,
    or collect data over multiple iterations and log it in a single step.

    By default, each call to `log` creates a new "step".
    The step must always increase, and it is not possible to log
    to a previous step. You can use any metric as the X axis in charts.
    See [Custom log axes](https://docs.wandb.ai/guides/track/log/customize-logging-axes/)
    for more details.

    In many cases, it is better to treat the W&B step like
    you'd treat a timestamp rather than a training step.

    ```python
    with wandb.init() as run:
        # Example: log an "epoch" metric for use as an X axis.
        run.log({"epoch": 40, "train-loss": 0.5})
    ```

    It is possible to use multiple `wandb.Run.log()` invocations to log to
    the same step with the `step` and `commit` parameters.
    The following are all equivalent:

    ```python
    with wandb.init() as run:
        # Normal usage:
        run.log({"train-loss": 0.5, "accuracy": 0.8})
        run.log({"train-loss": 0.4, "accuracy": 0.9})

        # Implicit step without auto-incrementing:
        run.log({"train-loss": 0.5}, commit=False)
        run.log({"accuracy": 0.8})
        run.log({"train-loss": 0.4}, commit=False)
        run.log({"accuracy": 0.9})

        # Explicit step:
        run.log({"train-loss": 0.5}, step=current_step)
        run.log({"accuracy": 0.8}, step=current_step)
        current_step += 1
        run.log({"train-loss": 0.4}, step=current_step)
        run.log({"accuracy": 0.9}, step=current_step)
    ```

    Args:
        data: A `dict` with `str` keys and values that are serializable
            Python objects including: `int`, `float` and `string`;
            any of the `wandb.data_types`; lists, tuples and NumPy arrays
            of serializable Python objects; other `dict`s of this
            structure.
        step: The step number to log. If `None`, then an implicit
            auto-incrementing step is used. See the notes in
            the description.
        commit: If true, finalize and upload the step. If false, then
            accumulate data for the step. See the notes in the description.
            If `step` is `None`, then the default is `commit=True`;
            otherwise, the default is `commit=False`.

    Examples:
    For more and more detailed examples, see
    [our guides to logging](https://docs.wandb.com/guides/track/log).

    Basic usage

    ```python
    import wandb

    with wandb.init() as run:
        run.log({"train-loss": 0.5, "accuracy": 0.9
    ```

    Incremental logging

    ```python
    import wandb

    with wandb.init() as run:
        run.log({"loss": 0.2}, commit=False)
        # Somewhere else when I'm ready to report this step:
        run.log({"accuracy": 0.8})
    ```

    Histogram

    ```python
    import numpy as np
    import wandb

    # sample gradients at random from normal distribution
    gradients = np.random.randn(100, 100)
    with wandb.init() as run:
        run.log({"gradients": wandb.Histogram(gradients)})
    ```

    Image from NumPy

    ```python
    import numpy as np
    import wandb

    with wandb.init() as run:
        examples = []
        for i in range(3):
            pixels = np.random.randint(low=0, high=256, size=(100, 100, 3))
            image = wandb.Image(pixels, caption=f"random field {i}")
            examples.append(image)
        run.log({"examples": examples})
    ```

    Image from PIL

    ```python
    import numpy as np
    from PIL import Image as PILImage
    import wandb

    with wandb.init() as run:
        examples = []
        for i in range(3):
            pixels = np.random.randint(
                low=0,
                high=256,
                size=(100, 100, 3),
                dtype=np.uint8,
            )
            pil_image = PILImage.fromarray(pixels, mode="RGB")
            image = wandb.Image(pil_image, caption=f"random field {i}")
            examples.append(image)
        run.log({"examples": examples})
    ```

    Video from NumPy

    ```python
    import numpy as np
    import wandb

    with wandb.init() as run:
        # axes are (time, channel, height, width)
        frames = np.random.randint(
            low=0,
            high=256,
            size=(10, 3, 100, 100),
            dtype=np.uint8,
        )
        run.log({"video": wandb.Video(frames, fps=4)})
    ```

    Matplotlib plot

    ```python
    from matplotlib import pyplot as plt
    import numpy as np
    import wandb

    with wandb.init() as run:
        fig, ax = plt.subplots()
        x = np.linspace(0, 10)
        y = x * x
        ax.plot(x, y)  # plot y = x^2
        run.log({"chart": fig})
    ```

    PR Curve

    ```python
    import wandb

    with wandb.init() as run:
        run.log({"pr": wandb.plot.pr_curve(y_test, y_probas, labels)})
    ```

    3D Object

    ```python
    import wandb

    with wandb.init() as run:
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
        wandb.Error: If called before `wandb.init()`.
        ValueError: If invalid data is passed.
    """
    ...

def save(
    glob_str: str | os.PathLike,
    base_path: str | os.PathLike | None = None,
    policy: PolicyName = "live",
) -> bool | list[str]:
    """Sync one or more files to W&B.

    Relative paths are relative to the current working directory.

    A Unix glob, such as "myfiles/*", is expanded at the time `save` is
    called regardless of the `policy`. In particular, new files are not
    picked up automatically.

    A `base_path` may be provided to control the directory structure of
    uploaded files. It should be a prefix of `glob_str`, and the directory
    structure beneath it is preserved.

    When given an absolute path or glob and no `base_path`, one
    directory level is preserved as in the example above.

    Files are automatically deduplicated: calling `save()` multiple times
    on the same file without modifications will not re-upload it.

    Args:
        glob_str: A relative or absolute path or Unix glob.
        base_path: A path to use to infer a directory structure; see examples.
        policy: One of `live`, `now`, or `end`.
        - live: upload the file as it changes, overwriting the previous version
        - now: upload the file once now
        - end: upload file when the run ends

    Returns:
        Paths to the symlinks created for the matched files.

        For historical reasons, this may return a boolean in legacy code.

    ```python
    import wandb

    run = wandb.init()

    run.save("these/are/myfiles/*")
    # => Saves files in a "these/are/myfiles/" folder in the run.

    run.save("these/are/myfiles/*", base_path="these")
    # => Saves files in an "are/myfiles/" folder in the run.

    run.save("/Users/username/Documents/run123/*.txt")
    # => Saves files in a "run123/" folder in the run. See note below.

    run.save("/Users/username/Documents/run123/*.txt", base_path="/Users")
    # => Saves files in a "username/Documents/run123/" folder in the run.

    run.save("files/*/saveme.txt")
    # => Saves each "saveme.txt" file in an appropriate subdirectory
    #    of "files/".

    # Explicitly finish the run since a context manager is not used.
    run.finish()
    ```
    """
    ...

def sweep(
    sweep: Union[dict, Callable],
    entity: Optional[str] = None,
    project: Optional[str] = None,
    prior_runs: Optional[List[str]] = None,
) -> str:
    """Initialize a hyperparameter sweep.

    Search for hyperparameters that optimizes a cost function
    of a machine learning model by testing various combinations.

    Make note the unique identifier, `sweep_id`, that is returned.
    At a later step provide the `sweep_id` to a sweep agent.

    See [Sweep configuration structure](https://docs.wandb.ai/guides/sweeps/define-sweep-configuration)
    for information on how to define your sweep.

    Args:
      sweep: The configuration of a hyperparameter search.
        (or configuration generator).
        If you provide a callable, ensure that the callable does
        not take arguments and that it returns a dictionary that
        conforms to the W&B sweep config spec.
      entity: The username or team name where you want to send W&B
        runs created by the sweep to. Ensure that the entity you
        specify already exists. If you don't specify an entity,
        the run will be sent to your default entity,
        which is usually your username.
      project: The name of the project where W&B runs created from
        the sweep are sent to. If the project is not specified, the
        run is sent to a project labeled 'Uncategorized'.
      prior_runs: The run IDs of existing runs to add to this sweep.

    Returns:
      str: A unique identifier for the sweep.
    """
    ...

def controller(
    sweep_id_or_config: Optional[Union[str, Dict]] = None,
    entity: Optional[str] = None,
    project: Optional[str] = None,
) -> _WandbController:
    """Public sweep controller constructor.

    Examples:
    ```python
    import wandb

    tuner = wandb.controller(...)
    print(tuner.sweep_config)
    print(tuner.sweep_id)
    tuner.configure_search(...)
    tuner.configure_stopping(...)
    ```
    """
    ...

def agent(
    sweep_id: str,
    function: Optional[Callable] = None,
    entity: Optional[str] = None,
    project: Optional[str] = None,
    count: Optional[int] = None,
) -> None:
    """Start one or more sweep agents.

    The sweep agent uses the `sweep_id` to know which sweep it
    is a part of, what function to execute, and (optionally) how
    many agents to run.

    Args:
        sweep_id: The unique identifier for a sweep. A sweep ID
            is generated by W&B CLI or Python SDK.
        function: A function to call instead of the "program"
            specified in the sweep config.
        entity: The username or team name where you want to send W&B
            runs created by the sweep to. Ensure that the entity you
            specify already exists. If you don't specify an entity,
            the run will be sent to your default entity,
            which is usually your username.
        project: The name of the project where W&B runs created from
            the sweep are sent to. If the project is not specified, the
            run is sent to a project labeled "Uncategorized".
        count: The number of sweep config trials to try.
    """
    ...

def define_metric(
    name: str,
    step_metric: str | wandb_metric.Metric | None = None,
    step_sync: bool | None = None,
    hidden: bool | None = None,
    summary: str | None = None,
    goal: str | None = None,
    overwrite: bool | None = None,
) -> wandb_metric.Metric:
    """Customize metrics logged with `wandb.Run.log()`.

    Args:
        name: The name of the metric to customize.
        step_metric: The name of another metric to serve as the X-axis
            for this metric in automatically generated charts.
        step_sync: Automatically insert the last value of step_metric into
            `wandb.Run.log()` if it is not provided explicitly. Defaults to True
             if step_metric is specified.
        hidden: Hide this metric from automatic plots.
        summary: Specify aggregate metrics added to summary.
            Supported aggregations include "min", "max", "mean", "last",
            "first", "best", "copy" and "none". "none" prevents a summary
            from being generated. "best" is used together with the goal
            parameter, "best" is deprecated and should not be used, use
            "min" or "max" instead. "copy" is deprecated and should not be
            used.
        goal: Specify how to interpret the "best" summary type.
            Supported options are "minimize" and "maximize". "goal" is
            deprecated and should not be used, use "min" or "max" instead.
        overwrite: If false, then this call is merged with previous
            `define_metric` calls for the same metric by using their
            values for any unspecified parameters. If true, then
            unspecified parameters overwrite values specified by
            previous calls.

    Returns:
        An object that represents this call but can otherwise be discarded.
    """
    ...

def log_artifact(
    artifact_or_path: Artifact | StrPath,
    name: str | None = None,
    type: str | None = None,
    aliases: list[str] | None = None,
    tags: list[str] | None = None,
) -> Artifact:
    """Declare an artifact as an output of a run.

    Args:
        artifact_or_path: (str or Artifact) A path to the contents of this artifact,
            can be in the following forms:
                - `/local/directory`
                - `/local/directory/file.txt`
                - `s3://bucket/path`
            You can also pass an Artifact object created by calling
            `wandb.Artifact`.
        name: (str, optional) An artifact name. Valid names can be in the following forms:
                - name:version
                - name:alias
                - digest
            This will default to the basename of the path prepended with the current
            run id  if not specified.
        type: (str) The type of artifact to log, examples include `dataset`, `model`
        aliases: (list, optional) Aliases to apply to this artifact,
            defaults to `["latest"]`
        tags: (list, optional) Tags to apply to this artifact, if any.

    Returns:
        An `Artifact` object.
    """
    ...

def use_artifact(
    artifact_or_name: str | Artifact,
    type: str | None = None,
    aliases: list[str] | None = None,
    use_as: str | None = None,
) -> Artifact:
    """Declare an artifact as an input to a run.

    Call `download` or `file` on the returned object to get the contents locally.

    Args:
        artifact_or_name: The name of the artifact to use. May be prefixed
            with the name of the project the artifact was logged to
            ("<entity>" or "<entity>/<project>"). If no
            entity is specified in the name, the Run or API setting's entity is used.
            Valid names can be in the following forms
        - name:version
        - name:alias
        type: The type of artifact to use.
        aliases: Aliases to apply to this artifact
        use_as: This argument is deprecated and does nothing.

    Returns:
        An `Artifact` object.

    Examples:
    ```python
    import wandb

    run = wandb.init(project="<example>")

    # Use an artifact by name and alias
    artifact_a = run.use_artifact(artifact_or_name="<name>:<alias>")

    # Use an artifact by name and version
    artifact_b = run.use_artifact(artifact_or_name="<name>:v<version>")

    # Use an artifact by entity/project/name:alias
    artifact_c = run.use_artifact(artifact_or_name="<entity>/<project>/<name>:<alias>")

    # Use an artifact by entity/project/name:version
    artifact_d = run.use_artifact(
        artifact_or_name="<entity>/<project>/<name>:v<version>"
    )

    # Explicitly finish the run since a context manager is not used.
    run.finish()
    ```
    """
    ...

def log_model(
    path: StrPath,
    name: str | None = None,
    aliases: list[str] | None = None,
) -> None:
    """Logs a model artifact containing the contents inside the 'path' to a run and marks it as an output to this run.

    The name of model artifact can only contain alphanumeric characters,
    underscores, and hyphens.

    Args:
        path: (str) A path to the contents of this model,
            can be in the following forms:
                - `/local/directory`
                - `/local/directory/file.txt`
                - `s3://bucket/path`
        name: A name to assign to the model artifact that
            the file contents will be added to. This will default to the
            basename of the path prepended with the current run id if
            not specified.
        aliases: Aliases to apply to the created model artifact,
                defaults to `["latest"]`

    Raises:
        ValueError: If name has invalid special characters.

    Returns:
        None
    """
    ...

def use_model(name: str) -> FilePathStr:
    """Download the files logged in a model artifact 'name'.

    Args:
        name: A model artifact name. 'name' must match the name of an existing logged
            model artifact. May be prefixed with `entity/project/`. Valid names
            can be in the following forms
        - model_artifact_name:version
        - model_artifact_name:alias

    Returns:
        path (str): Path to downloaded model artifact file(s).

    Raises:
        AssertionError: If model artifact 'name' is of a type that does
            not contain the substring 'model'.
    """
    ...

def link_model(
    path: StrPath,
    registered_model_name: str,
    name: str | None = None,
    aliases: list[str] | None = None,
) -> Artifact | None:
    """Log a model artifact version and link it to a registered model in the model registry.

    Linked model versions are visible in the UI for the specified registered model.

    This method will:
    - Check if 'name' model artifact has been logged. If so, use the artifact version that matches the files
    located at 'path' or log a new version. Otherwise log files under 'path' as a new model artifact, 'name'
    of type 'model'.
    - Check if registered model with name 'registered_model_name' exists in the 'model-registry' project.
    If not, create a new registered model with name 'registered_model_name'.
    - Link version of model artifact 'name' to registered model, 'registered_model_name'.
    - Attach aliases from 'aliases' list to the newly linked model artifact version.

    Args:
        path: (str) A path to the contents of this model, can be in the
            following forms:
        - `/local/directory`
        - `/local/directory/file.txt`
        - `s3://bucket/path`
        registered_model_name: The name of the registered model that the
            model is to be linked to. A registered model is a collection of
            model versions linked to the model registry, typically
            representing a team's specific ML Task. The entity that this
            registered model belongs to will be derived from the run.
        name: The name of the model artifact that files in 'path' will be
            logged to. This will default to the basename of the path
            prepended with the current run id  if not specified.
        aliases: Aliases that will only be applied on this linked artifact
            inside the registered model. The alias "latest" will always be
            applied to the latest version of an artifact that is linked.

    Raises:
        AssertionError: If registered_model_name is a path or
            if model artifact 'name' is of a type that does not contain
            the substring 'model'.
        ValueError: If name has invalid special characters.

    Returns:
        The linked artifact if linking was successful, otherwise `None`.
    """
    ...

def plot_table(
    vega_spec_name: str,
    data_table: wandb.Table,
    fields: dict[str, Any],
    string_fields: dict[str, Any] | None = None,
    split_table: bool = False,
) -> CustomChart:
    """Creates a custom charts using a Vega-Lite specification and a `wandb.Table`.

    This function creates a custom chart based on a Vega-Lite specification and
    a data table represented by a `wandb.Table` object. The specification needs
    to be predefined and stored in the W&B backend. The function returns a custom
    chart object that can be logged to W&B using `wandb.Run.log()`.

    Args:
        vega_spec_name: The name or identifier of the Vega-Lite spec
            that defines the visualization structure.
        data_table: A `wandb.Table` object containing the data to be
            visualized.
        fields: A mapping between the fields in the Vega-Lite spec and the
            corresponding columns in the data table to be visualized.
        string_fields: A dictionary for providing values for any string constants
            required by the custom visualization.
        split_table: Whether the table should be split into a separate section
            in the W&B UI. If `True`, the table will be displayed in a section named
            "Custom Chart Tables". Default is `False`.

    Returns:
        CustomChart: A custom chart object that can be logged to W&B. To log the
            chart, pass the chart object as argument to `wandb.Run.log()`.

    Raises:
        wandb.Error: If `data_table` is not a `wandb.Table` object.

    Example:
    ```python
    # Create a custom chart using a Vega-Lite spec and the data table.
    import wandb

    data = [[1, 1], [2, 2], [3, 3], [4, 4], [5, 5]]
    table = wandb.Table(data=data, columns=["x", "y"])
    fields = {"x": "x", "y": "y", "title": "MY TITLE"}

    with wandb.init() as run:
        # Training code goes here

        # Create a custom title with `string_fields`.
        my_custom_chart = wandb.plot_table(
            vega_spec_name="wandb/line/v0",
            data_table=table,
            fields=fields,
            string_fields={"title": "Title"},
        )

        run.log({"custom_chart": my_custom_chart})
    ```
    """
    ...

def watch(
    models: torch.nn.Module | Sequence[torch.nn.Module],
    criterion: torch.F | None = None,
    log: Literal["gradients", "parameters", "all"] | None = "gradients",
    log_freq: int = 1000,
    idx: int | None = None,
    log_graph: bool = False,
) -> None:
    """Hook into given PyTorch model to monitor gradients and the model's computational graph.

    This function can track parameters, gradients, or both during training.

    Args:
        models: A single model or a sequence of models to be monitored.
        criterion: The loss function being optimized (optional).
        log: Specifies whether to log "gradients", "parameters", or "all".
            Set to None to disable logging. (default="gradients").
        log_freq: Frequency (in batches) to log gradients and parameters. (default=1000)
        idx: Index used when tracking multiple models with `wandb.watch`. (default=None)
        log_graph: Whether to log the model's computational graph. (default=False)

    Raises:
        ValueError:
            If `wandb.init()` has not been called or if any of the models are not instances
            of `torch.nn.Module`.
    """
    ...

def unwatch(
    models: torch.nn.Module | Sequence[torch.nn.Module] | None = None,
) -> None:
    """Remove pytorch model topology, gradient and parameter hooks.

    Args:
        models: Optional list of pytorch models that have had watch called on them.
    """
    ...

def restore(
    name: str,
    run_path: str | None = None,
    replace: bool = False,
    root: str | None = None,
) -> None | TextIO:
    """Download the specified file from cloud storage.

    File is placed into the current directory or run directory.
    By default, will only download the file if it doesn't already exist.

    Args:
        name: The name of the file.
        run_path: Optional path to a run to pull files from, i.e. `username/project_name/run_id`
            if wandb.init has not been called, this is required.
        replace: Whether to download the file even if it already exists locally
        root: The directory to download the file to.  Defaults to the current
            directory or the run directory if wandb.init was called.

    Returns:
        None if it can't find the file, otherwise a file object open for reading.

    Raises:
        CommError: If W&B can't connect to the W&B backend.
        ValueError: If the file is not found or can't find run_path.
    """
    ...
