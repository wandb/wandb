## 0.8.2 (TBD)

#### :bug: Bug Fix

-   entity is persisted on wandb.run when queried from the server
-   tmp files always use the temporary directory to avoid syncing

#### :nail_care: Enhancement

-   summary now supports new dataframe format
-   WANDB_SILENT environment variable writes all wandb messages to debug.log
-   Improved error messages for windows and tensorboard logging
-   output.log is uploaded at the end of each run
-   metadata, requirements, and patches are uploaded at the beginning of a run

## 0.8.1 (May 23, 2019)

#### :bug: Bug Fix

-   wandb sync handles tensorboard embeddings
-   wandb sync correctly handles images in tensorboard
-   tf.keras correctly handles single input functional models
-   wandb.Api().runs returns an iterator that's reusable
-   WANDB_DIR within a hidden directory doesn't prevent syncing
-   run.files() iterates over all files
-   pytorch recurssion too deep error

#### :nail_care: Enhancement

-   wandb sync accepts an --ignore argument with globs to skip files
-   run.summary now has an items() method for iterating over all keys

## 0.8.0 (May 17, 2019)

#### :bug: Bug Fix

-   Better error messages on access denied
-   Better error messages when optional packages aren't installed
-   Urls printed to the termial are url-escaped
-   Namespaced tensorboard events work with histograms
-   Public API now retries on failures and re-uses connection pool
-   Catch git errors when remotes aren't pushed to origin
-   Moved keras graph collection to on_train_begin to handle unbuilt models
-   Handle more cases of not being able to save weights
-   Updates to summary after resuming are persisted
-   PyTorch histc logging fixed in 0.4.1
-   Fixed `wandb sync` tensorboard import

#### :nail_care: Enhancement

-   wandb.init(tensorboard=True) works with Tensorflow 2 and Eager Execution
-   wandb.init(tensorboard=True) now works with tb-nightly and PyTorch
-   Automatically log examples with tf.keras by adding missing validation_data
-   Socket only binds to localhost for improved security and prevents firewall warnings in OSX
-   Added user object to public api for getting the source user
-   Added run.display_name to the public api
-   Show display name in console output
-   Added --tags, --job_group, and --job_type to `wandb run`
-   Added environment variable for minimum time to run before considering crashed
-   Added flake8 tests to CI, thanks @cclauss!

## 0.7.3 (April 15, 2019)

#### :bug: Bug Fix

-   wandb-docker-run accepts image digests
-   keras callback works in tensorflow2-alpha0
-   keras model graph now puts input layer first

#### :nail_care: Enhancement

-   PyTorch log frequency added for gradients and weights
-   PyTorch logging performance enhancements
-   wandb.init now accepts a name parameter for naming runs
-   wandb.run.name reflects custom display names
-   Improvements to nested summary values
-   Deprecated wandb.Table.add_row in favor of wandb.Table.add_data
-   Initial support for a fast.ai callback thanks to @borisdayma!

## 0.7.2 (March 19, 2019)

#### :bug: Bug Fix

-   run.get_url resolves the default entity if one wasn't specified
-   wandb restore accepts run paths with only slashes
-   Fixed PyYaml deprecation warnings
-   Added entrypoint shell script to manifest
-   Strip newlines from cuda version

## 0.7.1 (March 14, 2019)

#### :bug: Bug Fix

-   handle case insensitive docker credentials
-   fix app_url for private cloud login flow
-   don't retry 404's when starting sweep agents

## 0.7.0 (February 28, 2019)

#### :bug: Bug Fix

-   ensure DNS lookup failures can't prevent startup
-   centralized debug logging
-   wandb agent waits longer to send a SIGKILL after sending SIGINT

#### :nail_care: Enhancement

-   support for logging docker images with the WANDB_DOCKER env var
-   WANDB_DOCKER automatically set when run in kubernetes
-   new wandb-docker-run command to automatically set env vars and mount code
-   wandb.restore supports launching docker for runs that ran with it
-   python packages are now recorded and saved in a requirements.txt file
-   cpu_count, gpu_count, gpu, os, and python version stored in wandb-metadata.json
-   the export api now supports docker-like paths, i.e. username/project:run_id
-   better first time user messages and login info

## 0.6.35 (January 29, 2019)

#### :bug: Bug Fix

-   Improve error reporting for sweeps

## 0.6.34 (January 23, 2019)

#### :bug: Bug Fix

-   fixed Jupyter logging, don't change logger level
-   fixed resuming in Jupyter

#### :nail_care: Enhancement

-   wandb.init now degrades gracefully if a user hasn't logged in to wandb
-   added a **force** flag to wandb.init to require a machine to be logged in
-   Tensorboard and TensorboardX logging is now automatically instrumented when enabled
-   added a **tensorboard** to wandb.init which patches tensorboard for logging
-   wandb.save handles now accepts a base path to files in sub directories
-   wandb.tensorflow and wandb.tensorboard can now be accessed without directly importing
-   `wandb sync` will now traverse a wandb run directory and sync all runs

## 0.6.33 (January 22, 2019)

#### :bug: Bug Fix

-   Fixed race where wandb process could hang at the end of a run

## 0.6.32 (December 22, 2018)

#### :bug: Bug Fix

-   Fix resuming in Jupyter on kernel restart
-   wandb.save ensures files are pushed regardless of growth

#### :nail_care: Enhancement

-   Added replace=True keyword to init for auto-resuming
-   New run.resumed property that can be used to detect if we're resuming
-   New run.step property to use for setting an initial epoch on resuming
-   Made Keras callback save the best model as it improves

## 0.6.31 (December 20, 2018)

#### :bug: Bug Fix

-   Really don't require numpy
-   Better error message if wandb.log is called before wandb.init
-   Prevent calling wandb.watch multiple times
-   Handle datetime attributes in logs / plotly

#### :nail_care: Enhancement

-   Add environment to sweeps
-   Enable tagging in the public API and in wandb.init
-   New media type wandb.Html for logging arbitrary html
-   Add Public api.create_run method for custom integrations
-   Added glob support to wandb.save, files save as they're written to
-   Added wandb.restore for pulling files on resume

## 0.6.30 (December 6, 2018)

#### :bug: Bug Fix

-   Added a timeout for generating diffs on large repos
-   Fixed edge case where file syncing could hang
-   Ensure all file changes are captured before exit
-   Handle cases of sys.exit where code isn't passed
-   Don't require numpy

#### :nail_care: Enhancement

-   New `wandb sync` command that pushes a local directory to the cloud
-   Support for syncing tfevents file during training
-   Detect when running as TFJob and auto group
-   New Kubeflow module with initial helpers for pipelines

## 0.6.29 (November 26, 2018)

#### :bug: Bug Fix

-   Fixed history / summary bug

## 0.6.28 (November 24, 2018)

#### :nail_care: Enhancement

-   Initial support for AWS SageMaker
-   `hook_torch` renamed to `watch` with a deprecation warning
-   Projects are automatically created if they don't exist
-   Additional GPU memory_allocated metric added
-   Keras Graph stores edges

#### :bug: Bug Fix

-   PyTorch graph parsing is more robust
-   Fixed PyTorch 0.3 support
-   File download API supports WANDB_API_KEY authentication

## 0.6.27 (November 13, 2018)

#### :nail_care: Enhancement

-   Sweeps work with new backend (early release).
-   Summary tracks all history metrics unless they're overridden by directly writing
    to summary.
-   Files support in data API.

#### :bug: Bug Fix

-   Show ongoing media file uploads in final upload progress.

## 0.6.26 (November 9, 2018)

#### :nail_care: Enhancement

-   wandb.Audio supports duration

#### :bug: Bug Fix

-   Pass username header in filestream API

## 0.6.25 (November 8, 2018)

#### :nail_care: Enhancement

-   New wandb.Audio data type.
-   New step keyword argument when logging metrics
-   Ability to specify run group and job type when calling wandb.init() or via
    environment variables. This enables automatic grouping of distributed training runs
    in the UI
-   Ability to override username when using a service account API key

#### :bug: Bug Fix

-   Handle non-tty environments in Python2
-   Handle non-existing git binary
-   Fix issue where sometimes the same image was logged twice during a Keras step

## 0.6.23 (October 19, 2018)

#### :nail_care: Enhancement

-   PyTorch
    -   Added a new `wandb.hook_torch` method which records the graph and logs gradients & parameters of pytorch models
    -   `wandb.Image` detects pytorch tensors and uses **torchvision.utils.make_grid** to render the image.

#### :bug: Bug Fix

-   `wandb restore` handles the case of not being run from within a git repo.

## 0.6.22 (October 18, 2018)

#### :bug: Bug Fix

-   We now open stdout and stderr in raw mode in Python 2 ensuring tools like bpdb work.

## 0.6.21 (October 12, 2018)

#### :nail_care: Enhancement

-   Catastrophic errors are now reported to Sentry unless WANDB_ERROR_REPORTING is set to false
-   Improved error handling and messaging on startup

## 0.6.20 (October 5, 2018)

#### :bug: Bug Fix

-   The first image when calling wandb.log was not being written, now it is
-   `wandb.log` and `run.summary` now remove whitespace from keys

## 0.6.19 (October 5, 2018)

#### :bug: Bug Fix

-   Vendored prompt_toolkit < 1.0.15 because the latest ipython is pinned > 2.0
-   Lazy load wandb.h5 only if `summary` is accessed to improve Data API performance

#### :nail_care: Enhancement

-   Jupyter
    -   Deprecated `wandb.monitor` in favor of automatically starting system metrics after the first wandb.log call
    -   Added new **%%wandb** jupyter magic method to display live results
    -   Removed jupyter description iframe
-   The Data API now supports `per_page` and `order` options to the `api.runs` method
-   Initial support for wandb.Table logging
-   Initial support for matplotlib logging
