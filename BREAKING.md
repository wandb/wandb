# Planned breaking changes

## Instructions for PR authors

Never merge a breaking change unless the next release bumps the minor version number (e.g. 0.18 => 0.19).

To plan a breaking change, do the following:

1. Add a deprecation warning
    - See ["Deprecating features" in CONTRIBUTING.md](CONTRIBUTING.md#deprecating-features)

2. Make it easy to switch to the new behavior
    - Best option: add a private setting whose default value uses or allows the deprecated behavior. You can enable this setting for dev versions. This reduces the breaking change to changing the default value of a setting, which the release manager can easily do
    - Alternative: create a PR that performs the breaking change. You can update and merge this PR prior to a release that can include breaking changes
    - Last resort: describe the change, but see note below first

2. List it under `Changes` in this file
    - If there's a setting, mention it and what value to set it to
    - If there's a PR, link to it
    - Mention yourself or anyone the SDK team can contact
    - Mention when the deprecation notice was added
    - Estimate when the change should happen (now + X months)

> [!NOTE]
> This is not an "ideas" file. This is only for changes for which all the hard work has already been done. Every change in the list must have an existing deprecation notice.

## Instructions for release manager

When preparing a patch release, ignore this file.

When preparing a release that can include breaking changes, consider applying changes from here. Check that enough time passed since the deprecation notice for any change. For any change you apply, remove it from the list below.

## Changes

- Make `--verify` the default for `wandb login`
    - PR: https://github.com/wandb/wandb/pull/9230
    - Owner: @jacobromero
    - Can do in >=0.20

- Remove `quiet` argument from `run.finish()`
    - Owner: @kptkin
    - Deprecated in 0.18.7 (https://github.com/wandb/wandb/pull/8794)
    - Can do in >=0.20

- Remove `summary="best"` from `run.define_metric()`
    - Owner: @kptkin
    - Deprecated in 0.17.9 (https://github.com/wandb/wandb/pull/8219)
    - Can do in >=0.20

- Remove `summary="copy"` from `run.define_metric()`
    - Owner: @timoffex
    - Deprecated in 0.17.6 (https://github.com/wandb/wandb/pull/8219)
    - Can do in >=0.20

- Remove `config_{exclude,include}_keys` from `wandb.init()`
    - Owner: @timoffex
    - Deprecated in 0.12.15 (https://github.com/wandb/wandb/pull/3510)
    - Can do in >=0.20

- Disallow boolean values from the `reinit` setting
    - Owner: @timoffex
    - Deprecated after 0.19.8 (https://github.com/wandb/wandb/pull/9557)
    - Can do after September 2025

- Deprecate `data_is_not_path` flag in `wandb.Html` and add `path` keyword argument to explicitly handle files paths.
    - Owner: @jacobromero
    - Deprecated after 0.19.9

- Remove fallback of storing system settings in a temporary directory when we don't have permissions to write to `~/.config/wandb/settings`
    - Owner: @jacobromero
    - Can do in >=0.20

- Require `format` argument when initializing `wandb.Video`
    - Owner: @jacobromero
    - Can do in >=0.20

- Remove the `start_method` setting:
    - Owner: @kptkin
    - Deprecated in 0.20.0 (https://github.com/wandb/wandb/pull/9837)
    - Can do in >=0.21

- Remove `RunDisabled` object:
    - Owner: @dmitryduev
    - Deprecated in 0.17.6 (https://github.com/wandb/wandb/pull/8064)
    - Can do in >=0.20

- Remove normalization of image data on `wandb.Image`
    - Owner: @jacobromero
    - Can do in >=0.21

- Disallow calling `wandb.save` without args:
    - Owner: @dmitryduev
    - Deprecated in 0.12.10 (https://github.com/wandb/wandb/pull/3028)
    - Can do in >=0.14

- Remove `wandb.Run::project_name()`:
    - Owner: @kptkin
    - Deprecated in 0.19.10 (https://github.com/wandb/wandb/pull/8925)
    - Can do in >=0.21

- Remove `wandb.Run::get_url()`:
    - Owner: @kptkin
    - Deprecated in 0.19.10 (https://github.com/wandb/wandb/pull/8925)
    - Can do in >=0.21

- Remove `wandb.Run::get_project_url()`:
    - Owner: @kptkin
    - Deprecated in 0.19.10 (https://github.com/wandb/wandb/pull/8925)
    - Can do in >=0.21

- Remove `wandb.Run::get_sweep_url()`:
    - Owner: @kptkin
    - Deprecated in 0.19.10 (https://github.com/wandb/wandb/pull/8925)
    - Can do in >=0.21

- Remove `wandb.apis.paginator.SizedPaginator::length`:
    - Owner: @jacobromero
    - Deprecated in 0.21.0
    - Can do in >=0.22

- Make `wandb.apis.public.runs.Run::load()` private:
    - Owner: @jacobromero
    - Can do in >=0.22

- Remove the `anonymous` setting and corresponding parameter from `wandb.init()` and `wandb.login()`:
    - Owner: @timoffex
    - Deprecated after 0.23.0
    - Can do after May 2026. It depends on when the PyTorch Lightning W&B integration (and possibly others) can be updated to not pass `anonymous` (even set to `None`)

- Use `.wandb` staging directory unconditionally in `wandb.Settings.wandb_dir` and deprecate + remove `wandb.Settings.use_dot_wandb`.
    - Owner: @dmitryduev
    - Can do in >= 0.24
