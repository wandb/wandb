## 0.11.1 (July 29, 2021)

#### :hourglass: Deprecated

- Python 3.5 will not be supported as of `wandb==0.12.0`

#### :bug: Bug Fix

- Reduce Memory Footprint of Images In Tables
- Added a dependency on graphql-core>=2.3.0
- Removed urllib3 pin to avoid conflicts, if you see urllib3 related errors run `pip install --upgrade urllib3`
- Improved Public API HTTP error messages
- Set run.dir to the generated directory name in disabled mode

#### :nail_care: Enhancement

- Adds support for native Jax array logging
- Tables now support Molecule data type
- Improve Stable-Baselines3 API by auto log model's name and always upload models at the end of training
- Implements the sweep local controller using wandb/sweeps

## 0.11.0 (July 15, 2021)

#### :hourglass: No Longer Supported

- Remove Python 2.7 support

#### :bug: Bug Fix

- Fix issue where `wandb.watch()` broke model saving in pytorch
- Fix issue where uniform sweep parameters were parsed as int_uniform
- Fix issue where file_stream thread was killed on 4xx errors

#### :nail_care: Enhancement

- Improve performance of artifact logging by making it non-blocking
- Add wandb integration for Stable-Baselines3
- Improve keras callback validation logging inference logic
- Expose sweep state via the public API
- Improve performance of sweep run fetches via the API

## 0.10.33 (June 28, 2021)

#### :bug: Bug Fix

- Fix issue where wandb restore 404ed if the run did not have a diff.patch file
- Fix issue where wandb.log raised an Exception after trying to log a pandas dataframe
- Fix issue where runs could be marked finished before files were finished uploading

#### :nail_care: Enhancement

- Disable reloading of run metadata (such as command) in resumed runs
- Allow logging of pandas dataframes by automatically converting them to W&B tables
- Fix up `log_code()` exclude fn to handle .wandb dir
- Improve handling of PyTorch model topology
- Increase config debounce interval to 30s to reduce load on WB/backend
- Improve reliability of CLI in generating sweeps with names, programs, and settings

## 0.10.32 (June 10, 2021)

#### :bug: Bug Fix

- Make `log_artifact()` more resilient to network errors
- Removed Duplicate Artifact Dependencies
- Workaround urlib3 issue on windows
- Fix regression where ipython was hanging
- Allow logging of numpy high precision floating point values
- Reduce liklyhood of collisions for file backed media or artifact objects
- Fix wandb.watch() regression when logging pytorch graphs

#### :nail_care: Enhancement

- Add support for logging joined and partitioned table
- Handle schema validation warnings for sweep configs
- Improve wandb sync to handle errors
- Add ability to label scripts and repositories who use wandb

## 0.10.31 (May 27, 2021)

#### :bug: Bug Fix

- wandb.login() did not properly persist the host parameter
- Fix issue where step information was not synced properly when syncing tensorboard directories
- Fix some unicode issues with python2.7
- Fixed bug in `plot_calibration_curve` for ComplementNB
- Fall back to not using SendFile on some linux systems
- Fix console issues where lines were truncated
- Fix console issues where console logging could block

#### :nail_care: Enhancement

- Add support for preemptible sweeps
- Add command line for sweep control
- Add support to load artifact collection properties

## 0.10.30 (May 7, 2021)

#### :bug: Bug Fix

- Found and fixed the remaining issues causing runs to be marked crashed during outages
- Improved performance for users of `define_metric`, pytorch-lightning, and aggressive config saving
- Fix issue when trying to log a cuda tensor to config or summary
- Remove dependancy on torch `backward_hooks` to compute graph
- Fix an issue preventing the ability to resume runs on sagemaker
- Fix issues preventing pdb from working reliably with wandb
- Fix deprecation warning in vendored library (user submission)
- Fix logging behavior where the library was accidently outputting logs to the console
- Fix disabled mode to not create wandb dir and log files
- Renamed types to prep for Tables launch

#### :nail_care: Enhancement

- Allow renaming groups with public api

## 0.10.29 (May 3, 2021)

#### :bug: Bug Fix

- Fix more network handling issues causing runs to be marked crashed (wandb sync to recover)
- Improve logging and exception handling to improve reporting and logging of crashed processes

## 0.10.28 (April 28, 2021)

#### :bug: Bug Fix

- Fix network handling issue causing runs to be marked crashed (wandb sync to recover)
- Use `register_full_backward_hook` to support models with Dict outputs
- Allow periods in table columns
- Fix artifact cache collisions when using forked processes
- Fix issue where custom charts do not display properly with pytorch-lightning

#### :nail_care: Enhancement

- Add experimental incremental artifact support
- Improve warnings when logging is being rate limited

## 0.10.27 (April 19, 2021)

#### :bug: Bug Fix

- Fix tensorboard_sync condition where metrics at end of short run are dropped 
- Fix `wandb sync` when tensorboard files are detected
- Fix api key prompt in databricks notebook

#### :nail_care: Enhancement

- Integrate DSViz into Keras WandbCallback
- Add support for conda dependencies (user submit)

## 0.10.26 (April 13, 2021)

#### :bug: Bug Fix

- Fix network handling issue where syncing stopped (use wandb sync to recover)
- Fix auth problem when using sagemaker and hugginface integrations together
- Fix handling of NaN values in tables with non floats
- Lazy load API object to prevent unnessary file access on module load

#### :nail_care: Enhancement

- Improve error messages when using public api history accessors

## 0.10.25 (April 5, 2021)

#### :bug: Bug Fix

- Fix possible artifact cache race when using parallel artifact reads
- Fix artifact reference when `checksum=False`

#### :nail_care: Enhancement

- Release `run.define_metric()` to simplify custom x-axis and more
- Add column operators `add_column`, `get_column`, `get_index` to `wandb.Table()`

## 0.10.24 (March 30, 2021)

#### :bug: Bug Fix

- Significant fixes to stdout/stderr console logging
- Prevent excessive network when saving files with policy=`live`
- Fix errors when trying to send large updates (most common with `wandb sync`)

#### :nail_care: Enhancement

- Automatically generate `run_table` artifact for logged tables
- Add bracket notation to artifacts
- Improve URL validation when specifying server url to `wandb login`

## 0.10.23 (March 22, 2021)

#### :bug: Bug Fix

- Fix logged artifacts to be accessible after wait()
- Fix spell.run integration
- Performance fix syncing console logs with carriage returns
- Fix confusion matrix with class names and unlabeled data

#### :nail_care: Enhancement

- Add the ability to save artifacts without creating a run
- Add Foreign Table References to wandb.Table
- Allow the same runtime object to be logged to multiple artifacts
- Add experimental `run._define_metric()` support
- Warn and ignore unsupported multiprocess `wandb.log()` calls

## 0.10.22 (March 9, 2021)

#### :bug: Bug Fix

- Fix system metric logging rate in 0.10.x
- Fix Audio external reference issue
- Fix short runs with tensorboard_sync
- Ignore `wandb.init(id=)` when running a sweep
- Sanitize artifact metadata if needed

#### :nail_care: Enhancement

- Allow syncing of tfevents with `wandb sync --sync-tensorboard`

## 0.10.21 (March 2, 2021)

#### :bug: Bug Fix

- Fix artifact.get() regression since 0.10.18
- Allow 0 byte artifacts
- Fix codesaving and program name reporting

#### :nail_care: Enhancement

- Added support for glb files for `wandb.Object3D()`
- Added support for external references for `wandb.Audio()`
- Custom chart support tensorboard `pr_curves` plugin
- Support saving entire code directory in an artifact

## 0.10.20 (February 22, 2021)

#### :bug: Bug Fix

- wandb.login() now respects disabled mode
- handle exception when trying to log TPUs in colab

#### :nail_care: Enhancement

- Add `WANDB_START_METHOD=thread` to support non-multiprocessing
- Add `group` and `job_type` to Run object in the export API
- Improve artifact docstrings

## 0.10.19 (February 14, 2021)

#### :bug: Bug Fix

- Fix artifact manifest files incorrectly named with patch suffix

## 0.10.18 (February 8, 2021)

#### :nail_care: Enhancement

- Add run delete and file delete to the public API
- Align steps between `tensorboard_sync` and wandb.log() history
- Add `WANDB_START_METHOD` to allow POSIX systems to use fork
- Support mixed types in wandb.Table() with `allow_mixed_types`

#### :bug: Bug Fix

- Fix potential leaked file due to log not being closed properly
- Improve `wandb verify` to better handle network issues and report errors
- Made file downloads more deterministic with respect to filesystem caches

## 0.10.17 (February 1, 2021)

#### :bug: Bug Fix

- Fix regression seen with python 3.5
- Silence vendored watchdog warnings on mac

## 0.10.16 (February 1, 2021)

#### :nail_care: Enhancement

- Artifacts now support parallel writers for large distributed workflows.
- Artifacts support distributed tables for dataset visualization.
- Improvements to PR templates
- Added more type annotations
- Vendored watchdog 0.9.0 removing it as a dependency
- New documentation generator
- Public api now has `file.direct_url` to avoid redirects for signed urls.

#### :bug: Bug Fix

- Allow `config-defaults.yaml` to be overwritten when running sweeps
- General bug fixes and improvements to `wandb verify`
- Disabled widgets in Spyder IDE
- Fixed WANDB_SILENT in Spyder IDE
- Reference file:// artifacts respect the `name` attribute.

## 0.10.15 (January 24, 2021)

#### :nail_care: Enhancement

- Add `wandb verify` to troubleshoot local installs

#### :bug: Bug Fix

- Fix tensorboard_sync issue writing to s3
- Prevent git secrets from being stored
- Disable verbose console messages when using moviepy
- Fix artifacts with checkpoints to be more robust when overwriting files
- Fix artifacts recycled id issue

## 0.10.14 (January 15, 2021)

#### :nail_care: Enhancement

- Add wandb.Audio support to Artifacts

#### :bug: Bug Fix

- Fix wandb config regressions introduced in 0.10.13
- Rollback changes supporting media with slashes in keys

## 0.10.13 (January 11, 2021)

#### :nail_care: Enhancement

- Add support for Mac M1 GPU monitoring
- Add support for TPU monitoring
- Add setting to disable sagemaker integration

#### :bug: Bug Fix

- Fix tensorboard_sync with tensorboardX and tf1
- Fix issues logging images with slashes
- Fix custom charts issues
- Improve error messages using `wandb pull`
- Improve error messages with `wandb.Table()`
- Make sure silent mode is silent
- Fix `wandb online` to renable logging
- Multiple artifact fixes

## 0.10.12 (December 3, 2020)

#### :nail_care: Enhancement

- Add Artifact.used_by and Artifact.logged_by
- Validate type consistency when logging Artifacts
- Enhance JoinedTable to not require downloaded assets
- Add ability to recursively download dependent artifacts
- Enable gradient logging with keras and tf2+
- Validate pytorch models are passed to wandb.watch()
- Improved docstrings for public methods / objects
- Warn when image sequences are logged with different sizes

#### :bug: Bug Fix

- Fix incorrectly generated filenames in summary
- Fix anonymous mode to include the api key in URLs
- Fix pickle issue with disabled mode
- Fix artifact from_id query
- Fix handling of Tables with different image paths

## 0.10.11 (November 18, 2020)

#### :nail_care: Enhancement

- Disable wandb logging with `wandb disabled` or `wandb.init(mode="disabled")`
- Support cloning an artifact when logging wandb.Image() 

#### :bug: Bug Fix

- Multiple media artifact improvements and internal refactor
- Improve handling of artifact errors
- Fix issue where notebook name was ignored
- Extend silent mode for jupyter logging
- Fix issue where vendored libraries interfered with python path
- Fix various exceptions (divide by zero, int conversion, TypeError)

## 0.10.10 (November 9, 2020)

#### :nail_care: Enhancement

- Added confusion matrix plot
- Better jupyter messages with wandb.init()/reinit/finish

#### :bug: Bug Fix

- Fix for fastai 2.1.5 (removed log_args)
- Fixed media logging when directories are changed

## 0.10.9 (November 4, 2020)

#### :nail_care: Enhancement

- Added artifact media logging (alpha)
- Add scriptable alerts
- Add url attribute for sweep public api
- Update docstrings for wandb sdk functions

#### :bug: Bug Fix

- Fix cases where offline mode was making network connections
- Fix issues with python sweeps and run stopping
- Fix logging issue where we could accidently display an api key
- Fix wandb login issues with malformed hosts
- Allow wandb.restore() to be called without wandb.init()
- Fix resuming (reusing run_id) with empty summary
- Fix artitifact download issue
- Add missing wandb.unwatch() function
- Avoid creating spurious wandb directories
- Fix collections import issue when using an old version of six

## 0.10.8 (October 22, 2020)

#### :nail_care: Enhancement

- Allow callables to be serialized

#### :bug: Bug Fix

- Fix compatibility issue with python 3.9
- Fix `wandb sync` failure introduced in 0.10.6
- Improve python agent handling of failing runs
- Fix rare condition where resuming runs does not work
- Improve symlink handling when called in thread context
- Fix issues when changing directories before calling wandb.init()

## 0.10.7 (October 15, 2020)

#### :bug: Bug Fix

- Fix issue when checking for updated releases on pypi

## 0.10.6 (October 15, 2020)

#### :bug: Bug Fix

- Make sure code saving is enabled in jupyter environments after login
- Sweep agents have extended timeout for large sweep configs
- Support WANDB_SILENT environment variable
- Warn about missing python package when logging images
- Fix wandb.restore() to apply diff patch
- Improve artifact error messages
- Fix loading of config-defaults.yaml and specified list of yaml config files

## 0.10.5 (October 7, 2020)

#### :nail_care: Enhancement

- Add new custom plots: `wandb.plot.*`
- Add new python based sweep agent: `wandb.agent()`

#### :bug: Bug Fix

- Console log fixes (tqdm on windows, fix close exceptions)
- Add more attributes to the Run object (group, job_type, urls)
- Fix sagemaker login issues
- Fix issue where plots were not uploaded until the end of run

## 0.10.4 (September 29, 2020)

#### :bug: Bug Fix

-  Fix an issue where wandb.init(allow_val_change=) throws exception

## 0.10.3 (September 29, 2020)

#### :nail_care: Enhancement

-  Added warning when trying to sync pre 0.10.0 run dirs
-  Improved jupyter support for wandb run syncing information

#### :bug: Bug Fix

-  Fix artifact download issues
-  Fix multiple issues with tensorboard_sync
-  Fix multiple issues with juypter/python sweeps
-  Fix issue where login was timing out
-  Fix issue where config was overwritten when resuming runs
-  Ported sacred observer to 0.10.x release
-  Fix predicted bounding boxes overwritten by ground truth boxes
-  Add missing save_code parameter to wandb.init()

## 0.10.2 (September 20, 2020)

#### :nail_care: Enhancement

-  Added upload_file to API
-  wandb.finish() can be called without matching wandb.init()

#### :bug: Bug Fix

-  Fix issue where files were being logged to wrong parallel runs
-  Fix missing properties/methods -- as_dict(), sweep_id
-  Fix wandb.summary.update() not updating all keys
-  Code saving was not properly enabled based on UI settings
-  Tensorboard now logging images before end of program
-  Fix resume issues dealing with config and summary metrics

## 0.10.1 (September 16, 2020)

#### :nail_care: Enhancement

-  Added sync_tensorboard ability to handle S3 and GCS files
-  Added ability to specify host with login
-  Improved artifact API to allow modifying attributes

#### :bug: Bug Fix

-  Fix codesaving to respect the server settings
-  Fix issue runing wandb.init() on restricted networks
-  Fix issue where we were ignoring settings changes
-  Fix artifact download issues

## 0.10.0 (September 11, 2020)

#### :nail_care: Enhancement

-  Added history sparklines at end of run
-  Artifact improvements and API for linking
-  Improved offline support and syncing
-  Basic noop mode support to simplify testing
-  Improved windows/pycharm support 
-  Run object has more modifiable properties
-  Public API supports attaching artifacts to historic runs

#### :bug: Bug Fix

-  Many bugs fixed due to simplifying logic

## 0.9.7 (September 8, 2020)

#### :nail_care: Enhancement

-  New sacred observer available at wandb.sacred.WandbObserver
-  Improved artifact reference tracking for HTTP urls

#### :bug: Bug Fix

-  Print meaningful error message when runs are queried with `summary` instead of `summary_metrics`

## 0.9.6 (August 28, 2020)

#### :nail_care: Enhancement

-  Sub paths of artifacts now expose an optional root directory argument to download()
-  Artifact.new_file accepts an optional mode argument
-  Removed legacy fastai docs as we're now packaged with fastai v2!

#### :bug: Bug Fix

-  Fix yaml parsing error handling logic
-  Bad spelling in torch docstring, thanks @mkkb473

## 0.9.5 (August 17, 2020)

#### :nail_care: Enhancement

-  Remove unused y_probas in sklearn plots, thanks @dreamflasher
-  New deletion apis for artifacts

#### :bug: Bug Fix

-  Fix `wandb restore` when not logged in
-  Fix artifact download paths on Windows
-  Retry 408 errors on upload
-  Fix mask numeric types, thanks @numpee
-  Fix artifact reference naming mixup

## 0.9.4 (July 24, 2020)
 
#### :nail_care: Enhancement

-  Default pytorch histogram logging frequency from 100 -> 1000 steps

#### :bug: Bug Fix

-  Fix multiple prompts for login when using the command line
-  Fix "no method rename_file" error
-  Fixed edgecase histogram calculation in PyTorch
-  Fix error in jupyter when saving session history
-  Correctly return artifact metadata in public api
-  Fix matplotlib / plotly rendering error

## 0.9.3 (July 10, 2020)

#### :nail_care: Enhancement

-   New artifact cli commands!
```shell
wandb artifact put path_file_or_ref
wandb artifact get artifact:version
wandb artifact ls project_name
```
-   New artifact api commands!
```python
wandb.log_artifact()
wandb.use_artifact()
wandb.Api().artifact_versions()
wandb.Api().run.used_artifacts()
wandb.Api().run.logged_artifacts()
wandb.Api().Artifact().file()
```
-   Improved syncing of large wandb-history.jsonl files for wandb sync
-   New Artifact.verify method to ensure the integrity of local artifacts
-   Better testing harness for api commands
-   Run directory now store local time instead of utc time in the name, thanks @aiyolo!
-   Improvements to our doc strings across the board.
-   wandb.Table now supports a `dataframe` argument for logging dataframes as tables!

#### :bug: Bug Fix

-   Artifacts work in python2
-   Artifacts default download locations work in Windows
-   GCS references now properly cache / download, thanks @yoks!
-   Fix encoding of numpy arrays to JSON
-   Fix string comparison error message

## 0.9.2 (June 29, 2020)

#### :nail_care: Enhancement

-   Major overhaul of artifact caching
-   Configurable cache directory for artifacts
-   Configurable download directory for artifacts
-   New Artifact.verify method to ensure the integrity of local artifacts
-   use_artifact no longer requires `type`
-   Deleted artifacts can now be be recommitted
-   Lidar scenes now support vectors

#### :bug: Bug Fix

-   Fix issue with artifact downloads returning errors.
-   Segmentation masks now handle non-unint8 data
-   Fixed path parsing logic in `api.runs()`

## 0.9.1 (June 9, 2020)

#### :bug: Bug Fix

-   Fix issue where files were always logged to latest run in a project.
-   Fix issue where url was not display url on first call to wandb.init

## 0.9.0 (June 5, 2020)

#### :bug: Bug Fix

-   Handle multiple inits in Jupyter
-   Handle ValueError's when capturing signals, thanks @jsbroks
-   wandb agent handles rate limiting properly

#### :nail_care: Enhancement

-   wandb.Artifact is now generally available!
-   feature_importances now supports CatBoost, thanks @neomatrix369

## 0.8.36 (May 11, 2020)

#### :bug: Bug Fix

-   Catch all exceptions when saving Jupyter sessions
-   validation_data automatically set in TF >= 2.2
-   _implements_\* hooks now implemented in keras callback for TF >= 2.2

#### :nail_care: Enhancement

-   Raw source code saving now disabled by default
-   We now support global settings on boot to enable code saving on the server
-   New `code_save=True` argument to wandb.init to enable code saving manually

## 0.8.35 (May 1, 2020)

#### :bug: Bug Fix

-   Ensure cells don't hang on completion
-   Fixed jupyter integration in PyCharm shells
-   Made session history saving handle None metadata in outputs

## 0.8.34 (Apr 28, 2020)

#### :nail_care: Enhancement

-   Save session history in jupyter notebooks
-   Kaggle internet enable notification
-   Extend wandb.plots.feature_importances to work with more model types, thanks @neomatrix369!

#### :bug: Bug Fix

-   Code saving for jupyter notebooks restored
-   Fixed thread errors in jupyter
-   Ensure final history rows aren't dropped in jupyter

## 0.8.33 (Apr 24, 2020)

#### :nail_care: Enhancement

-   Add default class labels for semantic segmentation
-   Enhance bounding box API to be similar to semantic segmentation API

#### :bug: Bug Fix

-   Increase media table rows to improve ROC/PR curve logging
-   Fix issue where pre binned histograms were not being handled properly
-   Handle nan values in pytorch histograms
-   Fix handling of binary image masks

## 0.8.32 (Apr 14, 2020)

#### :nail_care: Enhancement

-   Improve semantic segmentation image mask logging

## 0.8.31 (Mar 19, 2020)

#### :nail_care: Enhancement

-   Close all open files to avoice ResourceWarnings, thanks @CrafterKolyan!

#### :bug: Bug Fix

-   Parse "tensor" protobufs, fixing issues with tensorboard syncing in 2.1

## 0.8.30 (Mar 19, 2020)

#### :nail_care: Enhancement

-   Add ROC, precision_recall, HeatMap, explainText, POS, and NER to wandb.plots
-   Add wandb.Molecule() logging
-   Capture kaggle runs for metrics
-   Add ability to watch from run object

#### :bug: Bug Fix

-   Avoid accidently picking up global debugging logs

## 0.8.29 (Mar 5, 2020)

#### :nail_care: Enhancement

-   Improve bounding box annotations
-   Log active GPU system metrics
-   Only writing wandb/settings file if wandb init is called
-   Improvements to wandb local command

#### :bug: Bug Fix

-   Fix GPU logging on some devices without power metrics
-   Fix sweep config command handling
-   Fix tensorflow string logging

## 0.8.28 (Feb 21, 2020)

#### :nail_care: Enhancement

-   Added code saving of main python module
-   Added ability to specify metadata for bounding boxes and segmentation masks

#### :bug: Bug Fix

-   Fix situations where uncommited data from wandb.log() is not persisted

## 0.8.27 (Feb 11, 2020)

#### :bug: Bug Fix

-   Fix dependency conflict with new versions of six package

## 0.8.26 (Feb 10, 2020)

#### :nail_care: Enhancement

-   Add best metric and epoch to run summary with Keras callback
-   Added wandb.run.config_static for environments required pickled config

#### :bug: Bug Fix

-   Fixed regression causing failures with wandb.watch() and DataParallel
-   Improved compatibility with python 3.8
-   Fix model logging under windows

## 0.8.25 (Feb 4, 2020)

#### :bug: Bug Fix

-   Fix exception when using wandb.watch() in a notebook
-   Improve support for sparse tensor gradient logging on GPUs

## 0.8.24 (Feb 3, 2020)

#### :bug: Bug Fix

-   Relax version dependancy for PyYAML for users with old environments

## 0.8.23 (Feb 3, 2020)

#### :nail_care: Enhancement

-   Added scikit-learn support
-   Added ability to specify/exclude specific keys when building wandb.config

#### :bug: Bug Fix

-   Fix wandb.watch() on sparse tensors
-   Fix incompatibilty with ray 0.8.1
-   Fix missing pyyaml requirement
-   Fix "W&B process failed to launch" problems
-   Improved ability to log large model graphs and plots

## 0.8.22 (Jan 24, 2020)

#### :nail_care: Enhancement

-   Added ability to configure agent commandline from sweep config

#### :bug: Bug Fix

-   Fix fast.ai prediction logging
-   Fix logging of eager tensorflow tensors
-   Fix jupyter issues with logging notebook name and wandb.watch()

## 0.8.21 (Jan 15, 2020)

#### :nail_care: Enhancement

-   Ignore wandb.init() specified project and entity when running a sweep

#### :bug: Bug Fix

-   Fix agent "flapping" detection
-   Fix local controller not starting when sweep is pending

## 0.8.20 (Jan 10, 2020)

#### :nail_care: Enhancement

-   Added support for LightGBM
-   Added local board support (Experimental)
-   Added ability to modify sweep configuration
-   Added GPU power logging to system metrics

#### :bug: Bug Fix

-   Prevent sweep agent from failing continously when misconfigured

## 0.8.19 (Dec 18, 2019)

#### :nail_care: Enhancement

-   Added beta support for ray/tune hyperopt search strategy
-   Added ability to specify max runs per agent
-   Improve experience starting a sweep without a project already created

#### :bug: Bug Fix

-   Fix repeated wandb.Api().Run(id).scan_history() calls get updated data
-   Fix early_terminate/hyperband in notebook/python environments

## 0.8.18 (Dec 4, 2019)

#### :nail_care: Enhancement

-   Added min_step and max_step to run.scan_history for grabbing sub-sections of metrics
-   wandb.init(reinit=True) now automatically calls wandb.join() to better support multiple runs per process

#### :bug: Bug Fix

-   wandb.init(sync_tensorboard=True) works again for TensorFlow 2.0

## 0.8.17 (Dec 2, 2019)

#### :nail_care: Enhancement

-   Handle tags being passed in as a string

#### :bug: Bug Fix

-   Pin graphql-core < 3.0.0 to fix install errors
-   TQDM progress bars update logs properly
-   Oversized summary or history logs are now dropped which prevents retry hanging

## 0.8.16 (Nov 21, 2019)

#### :bug: Bug Fix

-   Fix regression syncing some versions of Tensorboard since 0.8.13
-   Fix network error in Jupyter

## 0.8.15 (Nov 5, 2019)

#### :bug: Bug Fix

-   Fix calling wandb.init with sync_tensorboard multiple times in Jupyter
-   Fix RuntimeError race when using threads and calling wandb.log
-   Don't initialize Sentry when error reporting is disabled

#### :nail_care: Enhancement

-   Added best_run() to wandb.sweep() public Api objects
-   Remove internal tracking keys from wandb.config objects in the public Api

## 0.8.14 (Nov 1, 2019)

#### :bug: Bug Fix

-   Improve large object warning when values reach maximum size
-   Warn when wandb.save isn't passed a string
-   Run stopping from the UI works since regressing in 0.8.12
-   Restoring a file that already exists locally works
-   Fixed TensorBoard incorrectly placing some keys in the wrong step since 0.8.10
-   wandb.Video only accepts uint8 instead of incorrectly converting to floats
-   SageMaker environment detection is now more robust
-   Resuming correctly populates config
-   wandb.restore respects root when run.dir is set #658
-   Calling wandb.watch multiple times properly namespaces histograms and graphs

#### :nail_care: Enhancement

-   Sweeps now work in Windows!
-   Added sweep attribute to Run in the public api
-   Added sweep link to Jupyter and terminal output
-   TensorBoard logging now stores proper timestamps when importing historic results
-   TensorBoard logging now supports configuring rate_limits and filtering event types
-   Use simple output mirroring stdout doesn't have a file descriptor
-   Write wandb meta files to the system temp directory if the local directory isn't writable
-   Added beta api.reports to the public API
-   Added wandb.unwatch to remove hooks from pytorch models
-   Store the framework used in config.\_wandb

## 0.8.13 (Oct 15, 2019)

#### :bug: Bug Fix

-   Create nested directory when videos are logged from tensorboard namespaces
-   Fix race when using wandb.log `async=True`
-   run.summary acts like a proper dictionary
-   run.summary sub dictionaries properly render
-   handle None when passing class_colors for segmentation masks
-   handle tensorflow2 not having a SessionHook
-   properly escape args in windows
-   fix hanging login when in anonymode
-   tf2 keras patch now handles missing callbacks args

#### :nail_care: Enhancement

-   Updates documentation autogenerated from docstrings in /docs
-   wandb.init(config=config_dict) does not update sweep specified parameters
-   wandb.config object now has a setdefaults method enabling improved sweep support
-   Improved terminal and jupyter message incorporating :rocket: emojii!
-   Allow wandb.watch to be called multiple times on different models
-   Improved support for watching multple tfevent files
-   Windows no longer requires `wandb run` simply run `python script_name.py`
-   `wandb agent` now works on windows.
-   Nice error message when wandb.log is called without a dict
-   Keras callback has a new `log_batch_frequency` for logging metrics every N batches

## 0.8.12 (Sep 20, 2019)

#### :bug: Bug Fix

-   Fix compatibility issue with python 2.7 and old pip dependencies

#### :nail_care: Enhancement

-   Improved onboarding flow when creating new accounts and entering api_key

## 0.8.11 (Sep 19, 2019)

#### :bug: Bug Fix

-   Fix public api returning incorrect data when config value is 0 or False
-   Resumed runs no longer overwrite run names with run id

#### :nail_care: Enhancement

-   Added recording of spell.run id in config

## 0.8.10 (Sep 13, 2019)

#### :bug: Bug Fix

-   wandb magic handles the case of tf.keras and keras being loaded
-   tensorboard logging won't drop steps if multiple loggers have different global_steps
-   keras gradient logging works in the latest tf.keras
-   keras validation_data is properly set in tensorflow 2
-   wandb pull command creates directories if they don't exist, thanks @chmod644
-   file upload batching now asserts a minimum size
-   sweeps works in python2 again
-   scan_history now iterates the full set of points
-   jupyter will run local mode if credentials can't be obtained

#### :nail_care: Enhancement

-   Sweeps can now be run from within jupyter / directly from python! https://docs.wandb.com/sweeps/python
-   New openai gym integration will automatically log videos, enabled with the monitor_gym keyword argument to wandb.init
-   Ray Tune logging callback in wandb.ray.WandbLogger
-   New global config file in ~/.config/wandb for global settings
-   Added tests for fastai, thanks @borisdayma
-   Public api performance enhancements
-   Deprecated username in favor of enitity in the public api for consistency
-   Anonymous login support enabled by default
-   New wandb.login method to be used in jupyter enabling anonymous logins
-   Better dependency error messages for data frames
-   Initial integration with spell.run
-   All images are now rendered as PNG to avoid JPEG artifacts
-   Public api now has a projects field

## 0.8.9 (Aug 19, 2019)

#### :bug: Bug Fix

-   run.summary updates work in jupyter before log is called
-   don't require numpy to be installed
-   Setting nested keys in summary works
-   notebooks in nested directories are properly saved
-   Don't retry 404's / better error messaging from the server
-   Strip leading slashes when loading paths in the public api

#### :nail_care: Enhancement

-   Small files are batch uploaded as gzipped tarballs
-   TensorBoardX gifs are logged to wandb

## 0.8.8 (Aug 13, 2019)

#### :bug: Bug Fix

-   wandb.init properly handles network failures on startup
-   Keras callback only logs examples if data_type or input_type is set
-   Fix edge case PyTorch model logging bug
-   Handle patching tensorboard multiple times in jupyter
-   Sweep picks up config.yaml from the run directory
-   Dataframes handle integer labels
-   Handle invalid JSON when querying jupyter servers

#### :nail_care: Enhancement

-   fastai uses a fixed seed for example logging
-   increased the max number of images for fastai callback
-   new wandb.Video tag for logging video
-   sync=False argument to wandb.log moves logging to a thread
-   New local sweep controller for custom search logic
-   Anonymous login support for easier onboarding
-   Calling wandb.init multiple times in jupyter doesn't error out

## 0.8.7 (Aug 7, 2019)

#### :bug: Bug Fix

-   keras callback no longer guesses input_type for 2D data
-   wandb.Image handles images with 1px height

#### :nail_care: Enhancement

-   wandb Public API now has `run.scan_history` to return all history rows
-   wandb.config prints helpful errors if used before calling init
-   wandb.summary prints helpful errors if used before calling init
-   filestream api points to new url on the backend

## 0.8.6 (July 31, 2019)

#### :bug: Bug Fix

-   fastai callback uses the default monitor instead of assuming val_loss
-   notebook introspections handles error cases and doesn't print stacktrace on failure
-   Don't print description warning when setting name
-   Fixed dataframe logging error with the keras callback
-   Fixed line offsets in logs when resuming runs
-   wandb.config casts non-builtins before writing to yaml
-   vendored backports.tempfile to address missing package on install

#### :nail_care: Enhancement

-   Added `api.sweep` to the python export api for querying sweeps
-   Added `WANDB_NOTEBOOK_NAME` for specifying the notebook name in cases we can't infer it
-   Added `WANDB_HOST` to override hostnames
-   Store if a run was run within jupyter
-   Client now supports stopping runs from the web ui
-   Handle floats passed as step to `wandb.log`
-   wandb.config has full unicode support
-   sync the main file to wandb if code saving is enabled and it's untracked by git
-   XGBoost callback: wandb.xgboost.wandb_callback()

## 0.8.5 (July 12, 2019)

#### :bug: Bug Fix

-   Fixed plotly charts with large numpy arrays not rendering
-   `wandb docker` works when nvidia is present
-   Better error when non string keys are sent to log
-   Relaxed pyyaml dependency to fix AMI installs
-   Magic works in jupyter notebooks.

#### :nail_care: Enhancement

-   New preview release of auto-dataframes for Keras
-   Added input_type and output_type to the Keras callback for simpler config
-   public api supports retrieving specific keys and custom xaxis

## 0.8.4 (July 8, 2019)

#### :bug: Bug Fix

-   WANDB_IGNORE_GLOBS is respected on the final scan of files
-   Unified run.id, run.name, and run.notes across all apis
-   Handle funky terminal sizes when setting up our psuedo tty
-   Fixed Jupyter notebook introspection logic
-   run.summary.update() persists changes to the server
-   tensorboard syncing is robust to invalid histograms and truncated files

#### :nail_care: Enhancement

-   preview release of magic, calling wandb.init(magic=True) should automatically track config and metrics when possible
-   cli now supports local installs of the backend
-   fastai callback supports logging example images

## 0.8.3 (June 26, 2019)

#### :bug: Bug Fix

-   image logging works in Windows
-   wandb sync handles tfevents with a single timestep
-   fix incorrect command in overview page for running runs
-   handle histograms with > 512 bins when streaming tensorboard
-   better error message when calling wandb sync on a file instead of a directory

#### :nail_care: Enhancement

-   new helper function for handling hyperparameters in sweeps `wandb.config.user_items()`
-   better mocking for improved testing

## 0.8.2 (June 20, 2019)

#### :bug: Bug Fix

-   entity is persisted on wandb.run when queried from the server
-   tmp files always use the temporary directory to avoid syncing
-   raise error if file shrinks while uploading
-   images log properly in windows
-   upgraded pyyaml requirement to address CVE
-   no longer store a history of rows to prevent memory leak

#### :nail_care: Enhancement

-   summary now supports new dataframe format
-   WANDB_SILENT environment variable writes all wandb messages to debug.log
-   Improved error messages for windows and tensorboard logging
-   output.log is uploaded at the end of each run
-   metadata, requirements, and patches are uploaded at the beginning of a run
-   when not running from a git repository, store the main python file
-   added WANDB_DISABLE_CODE to prevent diffing and code saving
-   when running in jupyter store the name of the notebook
-   auto-login support for colab
-   store url to colab notebook
-   store the version of this library in config
-   store sys.executable in metadata
-   fastai callback no longer requires path
-   wandb.init now accepts a notes argument
-   The cli replaced the message argument with notes and name

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
