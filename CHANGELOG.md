## 0.13.2 (August 22, 2022)

#### :bug: Bug Fix
* Fix issue triggered by colab update by using default file and catching exceptions by @raubitsj in https://github.com/wandb/wandb/pull/4156

**Full Changelog**: https://github.com/wandb/wandb/compare/v0.13.1...v0.13.2

## 0.13.1 (August 5, 2022)

#### :bug: Bug Fix
* Prevents run.log() from mutating passed in arguments by @kptkin in https://github.com/wandb/wandb/pull/4058

**Full Changelog**: https://github.com/wandb/wandb/compare/v0.13.0...v0.13.1

## 0.13.0 (August 4, 2022)

#### :nail_care: Enhancement
* Turns service on by default by @kptkin in https://github.com/wandb/wandb/pull/3895
* Adds support logic for handling server provided messages by @kptkin in https://github.com/wandb/wandb/pull/3706
* Allows runs to produce jobs on finish by @KyleGoyette in https://github.com/wandb/wandb/pull/3810
* Adds Job, QueuedRun and job handling in launch by @KyleGoyette in https://github.com/wandb/wandb/pull/3809
* Supports in launch agent of instance roles in ec2 and eks by @KyleGoyette in https://github.com/wandb/wandb/pull/3596
* Adds default behavior to the Keras Callback: always save model checkpoints as artifacts by @vwrj in https://github.com/wandb/wandb/pull/3909
* Sanitizes the artifact name in the KerasCallback for model artifact saving by @vwrj in https://github.com/wandb/wandb/pull/3927
* Improves console logging by moving emulator to the service process by @raubitsj in https://github.com/wandb/wandb/pull/3828
* Fixes data corruption issue when logging large sizes of data by @kptkin in https://github.com/wandb/wandb/pull/3920
* Adds the state to the Sweep repr in the Public API by @hu-po in https://github.com/wandb/wandb/pull/3948
* Adds an option to specify different root dir for git using settings or environment variables by @bcsherma in https://github.com/wandb/wandb/pull/3250
* Adds an option to pass `remote url` and `commit hash` as arguments to settings or as environment variables by @kptkin in https://github.com/wandb/wandb/pull/3934
* Improves time resolution for tracked metrics and for system metrics by @raubitsj in https://github.com/wandb/wandb/pull/3918
* Defaults to project name from the sweep config when project is not specified in the `wandb.sweep()` call by @hu-po in https://github.com/wandb/wandb/pull/3919
* Adds support to use namespace set user by the the launch agent by @KyleGoyette in https://github.com/wandb/wandb/pull/3950
* Adds telemetry to track when a run might be overwritten by @raubitsj in https://github.com/wandb/wandb/pull/3998
* Adds a tool to export `wandb`'s history into `sqlite` by @raubitsj in https://github.com/wandb/wandb/pull/3999
* Replaces some `Mapping[str, ...]` types with `NamedTuples` by @speezepearson in https://github.com/wandb/wandb/pull/3996
* Adds import hook for run telemetry by @kptkin in https://github.com/wandb/wandb/pull/3988
* Implements profiling support for IPUs by @cameron-martin in https://github.com/wandb/wandb/pull/3897
#### :bug: Bug Fix
* Fixes sweep agent with service by @raubitsj in https://github.com/wandb/wandb/pull/3899
* Fixes an empty type equals invalid type and how artifact dictionaries are handled by @KyleGoyette in https://github.com/wandb/wandb/pull/3904
* Fixes `wandb.Config` object to support default values when getting an attribute by @farizrahman4u in https://github.com/wandb/wandb/pull/3820
* Removes default config from jobs by @KyleGoyette in https://github.com/wandb/wandb/pull/3973
* Fixes an issue where patch is `None` by @KyleGoyette in https://github.com/wandb/wandb/pull/4003
* Fixes requirements.txt parsing in nightly SDK installation checks by @dmitryduev in https://github.com/wandb/wandb/pull/4012
* Fixes 409 Conflict handling when GraphQL requests timeout by @raubitsj in https://github.com/wandb/wandb/pull/4000
* Fixes service teardown handling if user process has been terminated by @raubitsj in https://github.com/wandb/wandb/pull/4024
* Adds `storage_path` and fixed `artifact.files` by @vanpelt in https://github.com/wandb/wandb/pull/3969
* Fixes performance issue syncing runs with a large number of media files by @vanpelt in https://github.com/wandb/wandb/pull/3941
#### :broom: Cleanup
* Adds an escape hatch logic to disable service by @kptkin in https://github.com/wandb/wandb/pull/3829
* Annotates `wandb/docker` and reverts change in the docker fixture by @dmitryduev in https://github.com/wandb/wandb/pull/3871
* Fixes GFLOPS to GFLOPs in the Keras `WandbCallback` by @ayulockin in https://github.com/wandb/wandb/pull/3913
* Adds type-annotate for `file_stream.py` by @dmitryduev in https://github.com/wandb/wandb/pull/3907
* Renames repository from `client` to `wandb` by @dmitryduev in https://github.com/wandb/wandb/pull/3977
* Updates documentation: adding `--report_to wandb` for HuggingFace Trainer by @ayulockin in https://github.com/wandb/wandb/pull/3959
* Makes aliases optional in link_artifact by @vwrj in https://github.com/wandb/wandb/pull/3986
* Renames `wandb local` to `wandb server` by @jsbroks in https://github.com/wandb/wandb/pull/3793
* Updates README badges by @raubitsj in https://github.com/wandb/wandb/pull/4023

## New Contributors
* @bcsherma made their first contribution in https://github.com/wandb/wandb/pull/3250
* @cameron-martin made their first contribution in https://github.com/wandb/wandb/pull/3897

**Full Changelog**: https://github.com/wandb/wandb/compare/v0.12.21...v0.13.0

## 0.12.21 (July 5, 2022)

#### :nail_care: Enhancement
* Fixes config not showing up until the run finish by @KyleGoyette in https://github.com/wandb/wandb/pull/3734
* Adds new types to the TypeRegistry to handling artifact objects in jobs and run configs by @KyleGoyette in https://github.com/wandb/wandb/pull/3806
* Adds new query to the the internal api getting the state of the run by @hu-po in https://github.com/wandb/wandb/pull/3799
* Replaces unsafe yaml loaders with yaml.safe_load by @zythosec in https://github.com/wandb/wandb/pull/3753
* Improves testing tooling by allowing to specify shards in manual testing  by @dmitryduev in https://github.com/wandb/wandb/pull/3826
* Fixes ROC and PR curves in the sklearn integration by stratifying sampling by @tylerganter in https://github.com/wandb/wandb/pull/3757
* Fixes input box in notebooks exceeding cell space by @dmitryduev in https://github.com/wandb/wandb/pull/3849
* Allows string to be passed as alias to link_model by @tssweeney in https://github.com/wandb/wandb/pull/3834
* Adds Support for FLOPS Calculation in `keras`'s `WandbCallback`  by @dmitryduev in https://github.com/wandb/wandb/pull/3869
* Extends python report editing by @andrewtruong in https://github.com/wandb/wandb/pull/3732
#### :bug: Bug Fix
* Fixes stats logger so it can find all the correct GPUs in child processes by @raubitsj in https://github.com/wandb/wandb/pull/3727
* Fixes regression in s3 reference upload for folders by @jlzhao27 in https://github.com/wandb/wandb/pull/3825
* Fixes artifact commit logic to handle collision in the backend by @speezepearson in https://github.com/wandb/wandb/pull/3843
* Checks for `None` response in the retry logic (safety check) by @raubitsj in https://github.com/wandb/wandb/pull/3863
* Adds sweeps on top of launch (currently in MVP) by @hu-po in https://github.com/wandb/wandb/pull/3669
* Renames functional tests dir and files by @raubitsj in https://github.com/wandb/wandb/pull/3879
#### :broom: Cleanup
* Fixes conditions order of `_to_dict` helper by @dmitryduev in https://github.com/wandb/wandb/pull/3772
* Fixes changelog broken link to PR 3709 by @janosh in https://github.com/wandb/wandb/pull/3786
* Fixes public api query (QueuedJob Api ) by @KyleGoyette in https://github.com/wandb/wandb/pull/3798
* Renames local runners to local-container and local-process by @hu-po in https://github.com/wandb/wandb/pull/3800
* Adds type annotations to files in the wandb/filesync directory by @speezepearson in https://github.com/wandb/wandb/pull/3774
* Re-organizes all the testing directories to have common root dir by @dmitryduev in https://github.com/wandb/wandb/pull/3740
* Fixes testing configuration and add bigger machine on `CircleCi` by @dmitryduev in https://github.com/wandb/wandb/pull/3836
* Fixes typo in the `wandb-service-user` readme file by @Co1lin in https://github.com/wandb/wandb/pull/3847
* Fixes broken artifact test for regression by @dmitryduev in https://github.com/wandb/wandb/pull/3857
* Removes unused files (relating to `py27`) and empty `submodules` declaration by @dmitryduev in https://github.com/wandb/wandb/pull/3850
* Adds extra for model reg dependency on cloudpickle by @tssweeney in https://github.com/wandb/wandb/pull/3866
* Replaces deprecated threading aliases by @hugovk in https://github.com/wandb/wandb/pull/3794
* Updates the `sdk` readme to the renamed (local -> server) commands by @sephmard in https://github.com/wandb/wandb/pull/3771

## New Contributors
* @janosh made their first contribution in https://github.com/wandb/wandb/pull/3786
* @Co1lin made their first contribution in https://github.com/wandb/wandb/pull/3847
* @tylerganter made their first contribution in https://github.com/wandb/wandb/pull/3757

**Full Changelog**: https://github.com/wandb/wandb/compare/v0.12.20...v0.12.21

## 0.12.20 (June 29, 2022)

#### :bug: Bug Fix
* Retry `commit_artifact` on conflict-error by @speezepearson in https://github.com/wandb/wandb/pull/3843

**Full Changelog**: https://github.com/wandb/wandb/compare/v0.12.19...v0.12.20

## 0.12.19 (June 22, 2022)

#### :bug: Bug Fix
* Fix regression in s3 reference upload for folders by @jlzhao27 in https://github.com/wandb/wandb/pull/3825

**Full Changelog**: https://github.com/wandb/wandb/compare/v0.12.18...v0.12.19

## 0.12.18 (June 9, 2022)

#### :nail_care: Enhancement
* Launch: BareRunner based on LocalRunner by @hu-po in https://github.com/wandb/wandb/pull/3577
* Add ability to specify api key to public api by @dannygoldstein in https://github.com/wandb/wandb/pull/3657
* Add support in artifacts for files with unicode on windows by @kptkin in https://github.com/wandb/wandb/pull/3650
* Added telemetry  for new packages by @manangoel99 in https://github.com/wandb/wandb/pull/3713
* Improve API key management by @vanpelt in https://github.com/wandb/wandb/pull/3718
* Add information about `wandb server` during login by @raubitsj in https://github.com/wandb/wandb/pull/3754

#### :bug: Bug Fix
* fix(weave): Natively support timestamps in Python Table Types by @dannygoldstein in https://github.com/wandb/wandb/pull/3606
* Add support for magic with service by @kptkin in https://github.com/wandb/wandb/pull/3623
* Add unit tests for DirWatcher and supporting classes by @speezepearson in https://github.com/wandb/wandb/pull/3589
* Improve `DirWatcher.update_policy` O(1) instead of O(num files uploaded) by @speezepearson in https://github.com/wandb/wandb/pull/3613
* Add argument to control what to log in SB3 callback by @astariul in https://github.com/wandb/wandb/pull/3643
* Improve parameter naming in sb3 integration by @dmitryduev in https://github.com/wandb/wandb/pull/3647
* Adjust the requirements for the dev environment setup on an M1 Mac by @dmitryduev in https://github.com/wandb/wandb/pull/3627
* Launch: Fix NVIDIA base image Linux keys by @KyleGoyette in https://github.com/wandb/wandb/pull/3637
* Fix launch run queue handling from config file by @KyleGoyette in https://github.com/wandb/wandb/pull/3636
* Fix issue where tfevents were not always consumed by @minyoung in https://github.com/wandb/wandb/pull/3673
* [Snyk] Fix for 8 vulnerabilities by @snyk-bot in https://github.com/wandb/wandb/pull/3695
* Fix s3 storage handler to upload folders when key names collide by @jlzhao27 in https://github.com/wandb/wandb/pull/3699
* Correctly load timestamps from tables in artifacts by @dannygoldstein in https://github.com/wandb/wandb/pull/3691
* Require `protobuf<4` by @dmitryduev in https://github.com/wandb/wandb/pull/3709
* Make Containers created through launch re-runnable as container jobs by @KyleGoyette in https://github.com/wandb/wandb/pull/3642
* Fix tensorboard integration skipping steps at finish() by @KyleGoyette in https://github.com/wandb/wandb/pull/3626
* Rename `wandb local` to `wandb server` by @jsbroks in https://github.com/wandb/wandb/pull/3716
* Fix busted docker inspect command by @vanpelt in https://github.com/wandb/wandb/pull/3742
* Add dedicated sentry wandb by @dmitryduev in https://github.com/wandb/wandb/pull/3724
* Image Type should gracefully handle older type params by @tssweeney in https://github.com/wandb/wandb/pull/3731

#### :broom: Cleanup
* Inline FileEventHandler.synced into the only method where it's used by @speezepearson in https://github.com/wandb/wandb/pull/3594
* Use passed size argument to make `PolicyLive.min_wait_for_size` a classmethod by @speezepearson in https://github.com/wandb/wandb/pull/3593
* Make FileEventHandler an ABC, remove some "default" method impls which were only used once by @speezepearson in https://github.com/wandb/wandb/pull/3595
* Remove unused field from DirWatcher by @speezepearson in https://github.com/wandb/wandb/pull/3592
* Make sweeps an extra instead of vendoring by @dmitryduev in https://github.com/wandb/wandb/pull/3628
* Add nightly CI testing by @dmitryduev in https://github.com/wandb/wandb/pull/3580
* Improve keras and data type Reference Docs by @ramit-wandb in https://github.com/wandb/wandb/pull/3676
* Update `pytorch` version requirements in dev environments by @dmitryduev in https://github.com/wandb/wandb/pull/3683
* Clean up CircleCI config by @dmitryduev in https://github.com/wandb/wandb/pull/3722
* Add `py310` testing in CI by @dmitryduev in https://github.com/wandb/wandb/pull/3730
* Ditch `dateutil` from the requirements by @dmitryduev in https://github.com/wandb/wandb/pull/3738
* Add deprecated string to `Table.add_row` by @nate-wandb in https://github.com/wandb/wandb/pull/3739

## New Contributors
* @sephmard made their first contribution in https://github.com/wandb/wandb/pull/3610
* @astariul made their first contribution in https://github.com/wandb/wandb/pull/3643
* @manangoel99 made their first contribution in https://github.com/wandb/wandb/pull/3713
* @nate-wandb made their first contribution in https://github.com/wandb/wandb/pull/3739

**Full Changelog**: https://github.com/wandb/wandb/compare/v0.12.17...v0.12.18

## 0.12.17 (May 26, 2022)

#### :bug: Bug Fix
* Update requirements to fix incompatibility with protobuf >= 4 by @dmitryduev in https://github.com/wandb/wandb/pull/3709

**Full Changelog**: https://github.com/wandb/wandb/compare/v0.12.16...v0.12.17

## 0.12.16 (May 3, 2022)

#### :nail_care: Enhancement
* Improve W&B footer by aligning summary/history in notebook env by @kptkin in https://github.com/wandb/wandb/pull/3479
* Enable experimental history step logging in artifacts by @raubitsj in https://github.com/wandb/wandb/pull/3502
* Add `args_no_boolean_flags` macro to sweep configuration by @hu-po in https://github.com/wandb/wandb/pull/3489
* Add logging support for `jax.bfloat.bfloat16` by @dmitryduev in https://github.com/wandb/wandb/pull/3528
* Raise exception when Table size exceeds limit by @dannygoldstein in https://github.com/wandb/wandb/pull/3511
* Add kaniko k8s builder for wandb launch by @KyleGoyette in https://github.com/wandb/wandb/pull/3492
* Add wandb.init() timeout setting by @kptkin in https://github.com/wandb/wandb/pull/3579
* Do not assume executable for given entrypoints with wandb launch by @KyleGoyette in https://github.com/wandb/wandb/pull/3461
* Jupyter environments no longer collect command arguments by @KyleGoyette in https://github.com/wandb/wandb/pull/3456
* Add support for TensorFlow/Keras SavedModel format by @ayulockin in https://github.com/wandb/wandb/pull/3276

#### :bug: Bug Fix
* Support version IDs in artifact refs, fix s3/gcs references in Windows by @annirudh in https://github.com/wandb/wandb/pull/3529
* Fix support for multiple finish for single run using wandb-service by @kptkin in https://github.com/wandb/wandb/pull/3560
* Fix duplicate backtrace when using wandb-service by @kptkin in https://github.com/wandb/wandb/pull/3575
* Fix wrong entity displayed in login message by @kptkin in https://github.com/wandb/wandb/pull/3490
* Fix hang when `wandb.init` is interrupted mid setup using wandb-service by @kptkin in https://github.com/wandb/wandb/pull/3569
* Fix handling keyboard interrupt to avoid hangs with wandb-service enabled by @kptkin in https://github.com/wandb/wandb/pull/3566
* Fix console logging with very long print out when using wandb-service by @kptkin in https://github.com/wandb/wandb/pull/3574
* Fix broken artifact string in launch init config by @KyleGoyette in https://github.com/wandb/wandb/pull/3582

#### :broom: Cleanup
* Fix typo in wandb.log() docstring by @RobRomijnders in https://github.com/wandb/wandb/pull/3520
* Cleanup custom chart code and add type annotations to plot functions by @kptkin in https://github.com/wandb/wandb/pull/3407
* Improve `wandb.init(settings=)` to handle `Settings` object similarly to `dict` parameter by @dmitryduev in https://github.com/wandb/wandb/pull/3510
* Add documentation note about api.viewer in api.user() and api.users() by @ramit-wandb in https://github.com/wandb/wandb/pull/3552
* Be explicit about us being py3+ only in setup.py by @dmitryduev in https://github.com/wandb/wandb/pull/3549
* Add type annotations to DirWatcher by @speezepearson in https://github.com/wandb/wandb/pull/3557
* Improve wandb.log() docstring to use the correct argument name by @idaho777 in https://github.com/wandb/wandb/pull/3585

## New Contributors
* @RobRomijnders made their first contribution in https://github.com/wandb/wandb/pull/3520
* @ramit-wandb made their first contribution in https://github.com/wandb/wandb/pull/3552
* @idaho777 made their first contribution in https://github.com/wandb/wandb/pull/3585

**Full Changelog**: https://github.com/wandb/wandb/compare/v0.12.15...v0.12.16

## 0.12.15 (April 21, 2022)

#### :nail_care: Enhancement
* Optimize wandb.Image logging when linked to an artifact by @tssweeney in https://github.com/wandb/wandb/pull/3418

**Full Changelog**: https://github.com/wandb/wandb/compare/v0.12.14...v0.12.15

## 0.12.14 (April 8, 2022)

#### :bug: Bug Fix
* Fix regression: disable saving history step in artifacts by @vwrj in https://github.com/wandb/wandb/pull/3495

**Full Changelog**: https://github.com/wandb/wandb/compare/v0.12.13...v0.12.14

## 0.12.13 (April 7, 2022)

#### :bug: Bug Fix
* Revert strictened api_key validation by @dmitryduev in https://github.com/wandb/wandb/pull/3485

**Full Changelog**: https://github.com/wandb/wandb/compare/v0.12.12...v0.12.13

## 0.12.12 (April 5, 2022)

#### :nail_care: Enhancement
* Allow run objects to be passed to other processes when using wandb-service by @kptkin in https://github.com/wandb/wandb/pull/3308
* Add create user to public api by @vanpelt in https://github.com/wandb/wandb/pull/3438
* Support logging from multiple processes with wandb-service by @kptkin in https://github.com/wandb/wandb/pull/3285
* Add gpus flag for local launch runner with cuda by @KyleGoyette in https://github.com/wandb/wandb/pull/3417
* Improve Launch deployable agent by @KyleGoyette in https://github.com/wandb/wandb/pull/3388
* Add Launch kubernetes integration by @KyleGoyette in https://github.com/wandb/wandb/pull/3393
* KFP: Add wandb visualization helper by @andrewtruong in https://github.com/wandb/wandb/pull/3439
* KFP: Link back to Kubeflow UI by @andrewtruong in https://github.com/wandb/wandb/pull/3427
* Add boolean flag arg macro by @hugo.ponte in https://github.com/wandb/wandb/pull/3489

#### :bug: Bug Fix
* Improve host / WANDB_BASE_URL validation by @dmitryduev in https://github.com/wandb/wandb/pull/3314
* Fix/insecure tempfile by @dmitryduev in https://github.com/wandb/wandb/pull/3360
* Fix excess warning span if requested WANDB_DIR/root_dir is not writable by @dmitryduev in https://github.com/wandb/wandb/pull/3304
* Fix line_series to plot array of strings by @kptkin in https://github.com/wandb/wandb/pull/3385
* Properly handle command line args with service by @kptkin in https://github.com/wandb/wandb/pull/3371
* Improve api_key validation by @dmitryduev in https://github.com/wandb/wandb/pull/3384
* Fix multiple performance issues caused by not using defaultdict by @dmitryduev in https://github.com/wandb/wandb/pull/3406
* Enable inf max jobs on launch agent by @stephchen in https://github.com/wandb/wandb/pull/3412
* fix colab command to work with launch by @stephchen in https://github.com/wandb/wandb/pull/3422
* fix typo in Config docstring by @hu-po in https://github.com/wandb/wandb/pull/3416
* Make code saving not a policy, keep previous custom logic by @dmitryduev in https://github.com/wandb/wandb/pull/3395
* Fix logging sequence images with service by @kptkin in https://github.com/wandb/wandb/pull/3339
* Add username to debug-cli log file to prevent conflicts of multiple users by @zythosec in https://github.com/wandb/wandb/pull/3301
* Fix python sweep agent for users of wandb service / pytorch-lightning by @raubitsj in https://github.com/wandb/wandb/pull/3465
* Remove unnecessary launch reqs checks by @KyleGoyette in https://github.com/wandb/wandb/pull/3457
* Workaround for MoviePy's Unclosed Writer by @tssweeney in https://github.com/wandb/wandb/pull/3471
* Improve handling of Run objects when service is not enabled by @kptkin in https://github.com/wandb/wandb/pull/3362

## New Contributors
* @hu-po made their first contribution in https://github.com/wandb/wandb/pull/3416
* @zythosec made their first contribution in https://github.com/wandb/wandb/pull/3301

**Full Changelog**: https://github.com/wandb/wandb/compare/v0.12.11...v0.12.12

## 0.12.11 (March 1, 2022)

#### :nail_care: Enhancement
* Add captions to Molecules by @dmitryduev in https://github.com/wandb/wandb/pull/3173
* Add CatBoost Integration by @ayulockin in https://github.com/wandb/wandb/pull/2975
* Launch: AWS Sagemaker integration by @KyleGoyette in https://github.com/wandb/wandb/pull/3007
* Launch: Remove repo2docker and add gpu support by @stephchen in https://github.com/wandb/wandb/pull/3161
* Adds Timestamp inference from Python for Weave by @tssweeney in https://github.com/wandb/wandb/pull/3212
* Launch GCP vertex integration by @stephchen in https://github.com/wandb/wandb/pull/3040
* Use Artifacts when put into run config. Accept a string to represent an artifact in the run config by @KyleGoyette in https://github.com/wandb/wandb/pull/3203
* Improve xgboost `wandb_callback` (#2929) by @ayulockin in https://github.com/wandb/wandb/pull/3025
* Add initial kubeflow pipeline support by @andrewtruong in https://github.com/wandb/wandb/pull/3206

#### :bug: Bug Fix
* Fix logging of images with special characters in the key by @speezepearson in https://github.com/wandb/wandb/pull/3187
* Fix azure blob upload retry logic by @vanpelt in https://github.com/wandb/wandb/pull/3218
* Fix program field for scripts run as a python module by @dmitryduev in https://github.com/wandb/wandb/pull/3228
* Fix issue where `sync_tensorboard` could die on large histograms by @KyleGoyette in https://github.com/wandb/wandb/pull/3019
* Fix wandb service performance issue during run shutdown by @raubitsj in https://github.com/wandb/wandb/pull/3262
* Fix vendoring of gql and graphql by @raubitsj in https://github.com/wandb/wandb/pull/3266
* Flush log data without finish with service by @kptkin in https://github.com/wandb/wandb/pull/3137
* Fix wandb service hang when the service crashes by @raubitsj in https://github.com/wandb/wandb/pull/3280
* Fix issue logging images with "/" on Windows by @KyleGoyette in https://github.com/wandb/wandb/pull/3146
* Add image filenames to images/separated media by @KyleGoyette in https://github.com/wandb/wandb/pull/3041
* Add setproctitle to requirements.txt by @raubitsj in https://github.com/wandb/wandb/pull/3289
* Fix issue where sagemaker run ids break run queues by @KyleGoyette in https://github.com/wandb/wandb/pull/3290
* Fix encoding exception when using %%capture magic by @raubitsj in https://github.com/wandb/wandb/pull/3310

## New Contributors
* @speezepearson made their first contribution in https://github.com/wandb/wandb/pull/3188

**Full Changelog**: https://github.com/wandb/wandb/compare/v0.12.10...v0.12.11

## 0.12.10 (February 1, 2022)

#### :nail_care: Enhancement
* Improve validation when creating Tables with invalid columns from dataframes by @tssweeney in https://github.com/wandb/wandb/pull/3113
* Enable digest deduplication for `use_artifact()` calls by @annirudh in https://github.com/wandb/wandb/pull/3109
* Initial prototype of azure blob upload support by @vanpelt in https://github.com/wandb/wandb/pull/3089

#### :bug: Bug Fix
* Fix wandb launch using python dev versions by @stephchen in https://github.com/wandb/wandb/pull/3036
* Fix loading table saved with mixed types by @vwrj in https://github.com/wandb/wandb/pull/3120
* Fix ResourceWarning when calling wandb.log by @vwrj in https://github.com/wandb/wandb/pull/3130
* Fix missing cursor in ProjectArtifactCollections by @KyleGoyette in https://github.com/wandb/wandb/pull/3108
* Fix windows table logging classes issue by @vwrj in https://github.com/wandb/wandb/pull/3145
* Gracefully handle string labels in wandb.sklearn.plot.classifier.calibration_curve by @acrellin in https://github.com/wandb/wandb/pull/3159
* Do not display login warning when calling wandb.sweep() by @acrellin in https://github.com/wandb/wandb/pull/3162

#### :broom: Cleanup
* Drop python2 backport deps (enum34, subprocess32, configparser) by @jbylund in https://github.com/wandb/wandb/pull/3004
* Settings refactor by @dmitryduev in https://github.com/wandb/wandb/pull/3083

## New Contributors
* @jbylund made their first contribution in https://github.com/wandb/wandb/pull/3004
* @acrellin made their first contribution in https://github.com/wandb/wandb/pull/3159

**Full Changelog**: https://github.com/wandb/wandb/compare/v0.12.9...v0.12.10

## 0.12.9 (December 16, 2021)

#### :bug: Bug Fix

- Fix regression in `upload_file()` exception handler by @raubitsj in https://github.com/wandb/wandb/pull/3059

**Full Changelog**: https://github.com/wandb/wandb/compare/v0.12.8...v0.12.9

## 0.12.8 (December 16, 2021)

#### :nail_care: Enhancement

- Update contributing guide and dev env setup tool by @dmitryduev in https://github.com/wandb/wandb/pull/2968
- Improve `wandb_callback` for LightGBM (#2945) by @ayulockin in https://github.com/wandb/wandb/pull/3024

#### :bug: Bug Fix

- Reduce GPU memory usage when generating histogram of model weights by @TOsborn in https://github.com/wandb/wandb/pull/2927
- Support mixed classes in bounding box and image mask annotation layers by @tssweeney in https://github.com/wandb/wandb/pull/2914
- Add max-jobs and launch async args by @stephchen in https://github.com/wandb/wandb/pull/2925
- Support lists of Summary objects encoded as strings to wandb.tensorboard.log by @dmitryduev in https://github.com/wandb/wandb/pull/2934
- Fix handling of 0 dim np arrays by @rpitonak in https://github.com/wandb/wandb/pull/2954
- Fix handling of empty default config file by @vwrj in https://github.com/wandb/wandb/pull/2957
- Add service backend using sockets (support fork) by @raubitsj in https://github.com/wandb/wandb/pull/2892
- Send git port along with url when sending git repo by @KyleGoyette in https://github.com/wandb/wandb/pull/2959
- Add support raw ip addresses for launch by @KyleGoyette in https://github.com/wandb/wandb/pull/2950
- Tables no longer serialize and hide 1d NDArrays by @tssweeney in https://github.com/wandb/wandb/pull/2976
- Fix artifact file uploads to S3 stores by @annirudh in https://github.com/wandb/wandb/pull/2999
- Send uploaded file list on file stream heartbeats by @annirudh in https://github.com/wandb/wandb/pull/2978
- Add support for keras experimental layers by @KyleGoyette in https://github.com/wandb/wandb/pull/2776
- Fix `from wandb import magic` to not require tensorflow by @raubitsj in https://github.com/wandb/wandb/pull/3021
- Fix launch permission error by @KyleGoyette in https://github.com/wandb/wandb/pull/3038

**Full Changelog**: https://github.com/wandb/wandb/compare/v0.12.7...v0.12.8

## 0.12.7 (November 18, 2021)

#### :bug: Bug Fix

- Fix issue where console log streaming was causing excessive network traffic by @vwrj in https://github.com/wandb/wandb/pull/2786
- Metaflow: Make optional dependencies actually optional by @andrewtruong in https://github.com/wandb/wandb/pull/2842
- Fix docstrings for wandb.watch and ValidationDataLogger by @charlesfrye in https://github.com/wandb/wandb/pull/2849
- Prevent launch agent from sending runs to a different project or entity by @KyleGoyette in https://github.com/wandb/wandb/pull/2872
- Fix logging pr_curves through tensorboard by @KyleGoyette in https://github.com/wandb/wandb/pull/2876
- Prevent TPU monitoring from reporting invalid metrics when not available by @kptkin in https://github.com/wandb/wandb/pull/2753
- Make import order dependencies for WandbCallback more robust by @kptkin in https://github.com/wandb/wandb/pull/2807
- Fix a bug in feature importance plotting to handle matrices of different shapes by @dannygoldstein in https://github.com/wandb/wandb/pull/2811
- Fix base url handling to allow trailing / by @kptkin in https://github.com/wandb/wandb/pull/2910
- Prevent wandb.agent() from sending too many heartbeats impacting rate limits by @dannygoldstein in https://github.com/wandb/wandb/pull/2923
- Redact sensitive information from debug logs by @raubitsj in https://github.com/wandb/wandb/pull/2931

#### :nail_care: Enhancement

- Add wandb.Molecule support for rdkit supported formats by @dmitryduev in https://github.com/wandb/wandb/pull/2902
- Add module-level docstrings for reference doc modules. by @charlesfrye in https://github.com/wandb/wandb/pull/2847
- Store launch metadata in file by @KyleGoyette in https://github.com/wandb/wandb/pull/2582
- Add Project.sweeps() public API call to view all sweeps in a project by @stephchen in https://github.com/wandb/wandb/pull/2729
- Ensures API key prompt remains captive when user enters nothing by @dannygoldstein in https://github.com/wandb/wandb/pull/2721
- Refactors wandb.sklearn into submodules by @charlesfrye in https://github.com/wandb/wandb/pull/2869
- Support code artifacts in wandb launch by @KyleGoyette in https://github.com/wandb/wandb/pull/2860
- Improve launch agent (async, stop, heartbeat updates) by @stephchen in https://github.com/wandb/wandb/pull/2871
- Improve usage and error messages for anonymous mode by @kimjyhello in https://github.com/wandb/wandb/pull/2823
- Add example on how to find runs with wandb.Api().runs(...) matching a regex by @dmitryduev in https://github.com/wandb/wandb/pull/2926

**Full Changelog**: https://github.com/wandb/wandb/compare/v0.12.6...v0.12.7

## 0.12.6 (October 27, 2021)

#### :bug: Bug Fix

- Fix sklearn `plot_calibration_curve()` issue breaking the provided model by @vwrj in https://github.com/wandb/wandb/pull/2791
- Fix CondaEnvExportError by redirecting stderr by @charlesfrye in https://github.com/wandb/wandb/pull/2814
- Fix `use_artifact()` when specifying an artifact from a different project by @KyleGoyette in https://github.com/wandb/wandb/pull/2832

#### :nail_care: Enhancement

- Add metric names to pr curve charts in tensorboard by @vanpelt in https://github.com/wandb/wandb/pull/2822

**Full Changelog**: https://github.com/wandb/wandb/compare/v0.12.5...v0.12.6

## 0.12.5 (October 19, 2021)

#### :bug: Bug Fix

- Report errors for invalid characters in logged media keys on windows
- Handle errors when probing for TPUs in unsupported environments
- Fixed bug where `%%wandb` followed by wandb.init() does not display run links
- Fixed api.runs() to correctly return all runs for the current entity/project

#### :nail_care: Enhancement

- Add `wandb.require(experiment="service")` to improve multiprocessing support
- Add support for swappable artifacts in launch context
- Add `wandb.login(timeout=)` support for jupyter environments
- Add ability to disable git ref saving with `WANDB_DISABLE_GIT`
- Support newer versions of pytest-mock and PyYAML
- Add ability to delete artifacts with aliases: `artifact.delete(delete_aliases=True)`
- Add `unwatch()` method to the Run object

## 0.12.4 (October 5, 2021)

#### :bug: Bug Fix

- Fix regression introduced in 0.12.2 causing network access when `WANDB_MODE=offline`

## 0.12.3 (September 30, 2021)

#### :bug: Bug Fix

- Fixes the grid search stopping condition in the local controller

#### :nail_care: Enhancement

- New jupyter magic for displaying runs, sweeps, and projects `%wandb path/to/run -h 1024`
- We no longer display run iframe by default in jupyter, add `%%wandb` to a cell to display a run
- Makes api key prompting retry indefinitely on malformed input
- Invite users to teams via the api `api.team("team_name").invite("username_or_email")`
- Remove users from a team via the api `api.team("team_name").members[0].delete()`
- Create service accounts via the api `api.team("team_name").create_service_account("Description")`
- Manage api keys via the api `api.user("username_or_email").generate_api_key()`
- Add pytorch profiling trace support with `wandb.profiler.torch_trace_handler()`

## 0.12.2 (September 15, 2021)

#### :bug: Bug Fix

- Fix tensorboard_sync to handle ephemeral Sagemaker tfevents files
- Fix Reports query from the public api (broken pagination and report path)
- Fix `wandb.login()` when relogin is specified (only force login once)

#### :nail_care: Enhancement

- Clean up footer output of summary and history metrics
- Clean up error message from `wandb sweep --update`
- Add warning for `wandb local` users to update their docker
- Add optional argument log_learning_curve to wandb.sklearn.plot_classifier()
- Restore frozen pip package versions when using `wandb launch`
- Add support for jupyter notebooks in launch
- Add `wandb.login()` timeout option

## 0.12.1 (August 26, 2021)

#### :bug: Bug Fix

- Fix tensorflow/keras 2.6 not logging validation examples
- Fix metrics logged through tensorboard not supporting time on x-axis
- Fix `WANDB_IGNORE_GLOBS` environment variable handling
- Fix handling when sys.stdout is configured to a custom logger
- Fix sklearn feature importance plots not matching feature names properly
- Fix an issue where colab urls were not being captured
- Save program commandline if run executable was outside cwd

#### :nail_care: Enhancement

- Add Prodigy integration to upload annotated datasets to W&B Tables
- Add initial Metaflow support
- Add experimental wandb launch support
- Add warnings that public API requests are timing out and allow override
- Improve error handling in local controller sweeps engine

## 0.12.0 (August 10, 2021)

#### :hourglass: No Longer Supported

- Remove Python 3.5 support

#### :bug: Bug Fix

- Fix issue that could cause artifact uploads to fail if artifact files are being modified
- Fix issue where `wandb.restore()` wouldn't work with runs from a sweep

#### :nail_care: Enhancement

- Improve run execution time calculation

## 0.11.2 (August 2, 2021)

#### :bug: Bug Fix

- Restore vendored graphql-core library because of network regression

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
-   wandb now supports stopping runs from the web ui
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
