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
