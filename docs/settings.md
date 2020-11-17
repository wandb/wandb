---
title: Settings
---

<a name="wandb.sdk.wandb_settings"></a>
# wandb.sdk.wandb\_settings

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_settings.py#L2)

This module configures settings for wandb runs.

Order of loading settings: (differs from priority)
defaults
environment
wandb.setup(settings=)
system_config
workspace_config
wandb.init(settings=)
network_org
network_entity
network_project

Priority of settings:  See "source" variable.

When override is used, it has priority over non-override settings

Override priorities are in the reverse order of non-override settings

<a name="wandb.sdk.wandb_settings.defaults"></a>
#### defaults

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_settings.py#L59)

<a name="wandb.sdk.wandb_settings.env_prefix"></a>
#### env\_prefix

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_settings.py#L67)

<a name="wandb.sdk.wandb_settings.env_settings"></a>
#### env\_settings

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_settings.py#L69)

<a name="wandb.sdk.wandb_settings.env_convert"></a>
#### env\_convert

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_settings.py#L96)

<a name="wandb.sdk.wandb_settings.get_wandb_dir"></a>
#### get\_wandb\_dir

```python
get_wandb_dir(root_dir: str)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_settings.py#L157)

<a name="wandb.sdk.wandb_settings.SettingsConsole"></a>
## SettingsConsole Objects

```python
@enum.unique
class SettingsConsole(enum.Enum)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_settings.py#L181)

<a name="wandb.sdk.wandb_settings.SettingsConsole.OFF"></a>
#### OFF

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_settings.py#L182)

<a name="wandb.sdk.wandb_settings.SettingsConsole.WRAP"></a>
#### WRAP

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_settings.py#L183)

<a name="wandb.sdk.wandb_settings.SettingsConsole.REDIRECT"></a>
#### REDIRECT

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_settings.py#L184)

<a name="wandb.sdk.wandb_settings.Settings"></a>
## Settings Objects

```python
class Settings(object)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_settings.py#L187)

Settings Constructor

**Arguments**:

- `entity` - personal user or team to use for Run.
- `project` - project name for the Run.


**Raises**:

- `Exception` - if problem.

<a name="wandb.sdk.wandb_settings.Settings.mode"></a>
#### mode

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_settings.py#L198)

<a name="wandb.sdk.wandb_settings.Settings.console"></a>
#### console

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_settings.py#L199)

<a name="wandb.sdk.wandb_settings.Settings.disabled"></a>
#### disabled

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_settings.py#L200)

<a name="wandb.sdk.wandb_settings.Settings.run_tags"></a>
#### run\_tags

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_settings.py#L201)

<a name="wandb.sdk.wandb_settings.Settings.resume_fname_spec"></a>
#### resume\_fname\_spec

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_settings.py#L203)

<a name="wandb.sdk.wandb_settings.Settings.root_dir"></a>
#### root\_dir

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_settings.py#L204)

<a name="wandb.sdk.wandb_settings.Settings.log_dir_spec"></a>
#### log\_dir\_spec

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_settings.py#L205)

<a name="wandb.sdk.wandb_settings.Settings.log_user_spec"></a>
#### log\_user\_spec

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_settings.py#L206)

<a name="wandb.sdk.wandb_settings.Settings.log_internal_spec"></a>
#### log\_internal\_spec

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_settings.py#L207)

<a name="wandb.sdk.wandb_settings.Settings.sync_file_spec"></a>
#### sync\_file\_spec

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_settings.py#L208)

<a name="wandb.sdk.wandb_settings.Settings.sync_dir_spec"></a>
#### sync\_dir\_spec

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_settings.py#L209)

<a name="wandb.sdk.wandb_settings.Settings.files_dir_spec"></a>
#### files\_dir\_spec

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_settings.py#L210)

<a name="wandb.sdk.wandb_settings.Settings.log_symlink_user_spec"></a>
#### log\_symlink\_user\_spec

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_settings.py#L211)

<a name="wandb.sdk.wandb_settings.Settings.log_symlink_internal_spec"></a>
#### log\_symlink\_internal\_spec

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_settings.py#L212)

<a name="wandb.sdk.wandb_settings.Settings.sync_symlink_latest_spec"></a>
#### sync\_symlink\_latest\_spec

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_settings.py#L213)

<a name="wandb.sdk.wandb_settings.Settings.settings_system_spec"></a>
#### settings\_system\_spec

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_settings.py#L214)

<a name="wandb.sdk.wandb_settings.Settings.settings_workspace_spec"></a>
#### settings\_workspace\_spec

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_settings.py#L215)

<a name="wandb.sdk.wandb_settings.Settings.silent"></a>
#### silent

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_settings.py#L216)

<a name="wandb.sdk.wandb_settings.Settings.show_info"></a>
#### show\_info

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_settings.py#L217)

<a name="wandb.sdk.wandb_settings.Settings.show_warnings"></a>
#### show\_warnings

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_settings.py#L218)

<a name="wandb.sdk.wandb_settings.Settings.show_errors"></a>
#### show\_errors

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_settings.py#L219)

<a name="wandb.sdk.wandb_settings.Settings.Source"></a>
## Source Objects

```python
@enum.unique
class Source(enum.IntEnum)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_settings.py#L233)

<a name="wandb.sdk.wandb_settings.Settings.Source.BASE"></a>
#### BASE

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_settings.py#L234)

<a name="wandb.sdk.wandb_settings.Settings.Source.ORG"></a>
#### ORG

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_settings.py#L235)

<a name="wandb.sdk.wandb_settings.Settings.Source.ENTITY"></a>
#### ENTITY

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_settings.py#L236)

<a name="wandb.sdk.wandb_settings.Settings.Source.PROJECT"></a>
#### PROJECT

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_settings.py#L237)

<a name="wandb.sdk.wandb_settings.Settings.Source.USER"></a>
#### USER

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_settings.py#L238)

<a name="wandb.sdk.wandb_settings.Settings.Source.SYSTEM"></a>
#### SYSTEM

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_settings.py#L239)

<a name="wandb.sdk.wandb_settings.Settings.Source.WORKSPACE"></a>
#### WORKSPACE

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_settings.py#L240)

<a name="wandb.sdk.wandb_settings.Settings.Source.ENV"></a>
#### ENV

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_settings.py#L241)

<a name="wandb.sdk.wandb_settings.Settings.Source.SETUP"></a>
#### SETUP

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_settings.py#L242)

<a name="wandb.sdk.wandb_settings.Settings.Source.LOGIN"></a>
#### LOGIN

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_settings.py#L243)

<a name="wandb.sdk.wandb_settings.Settings.Source.INIT"></a>
#### INIT

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_settings.py#L244)

<a name="wandb.sdk.wandb_settings.Settings.Source.SETTINGS"></a>
#### SETTINGS

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_settings.py#L245)

<a name="wandb.sdk.wandb_settings.Settings.Source.ARGS"></a>
#### ARGS

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_settings.py#L246)

<a name="wandb.sdk.wandb_settings.Settings.Console"></a>
#### Console

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_settings.py#L248)

<a name="wandb.sdk.wandb_settings.Settings.__init__"></a>
#### \_\_init\_\_

```python
 | __init__(base_url: str = None, api_key: str = None, anonymous=None, mode: str = None, entity: str = None, project: str = None, run_group: str = None, run_job_type: str = None, run_id: str = None, run_name: str = None, run_notes: str = None, resume: str = None, magic: Union[Dict, str, bool] = False, run_tags: Sequence = None, sweep_id=None, allow_val_change: bool = None, force: bool = None, relogin: bool = None, problem="fatal", system_sample_seconds=2, system_samples=15, heartbeat_seconds=30, config_paths=None, _config_dict=None, root_dir=None, settings_system_spec="~/.config/wandb/settings", settings_workspace_spec="{wandb_dir}/settings", sync_dir_spec="{wandb_dir}/{run_mode}-{timespec}-{run_id}", sync_file_spec="run-{run_id}.wandb", sync_symlink_latest_spec="{wandb_dir}/latest-run", log_dir_spec="{wandb_dir}/{run_mode}-{timespec}-{run_id}/logs", log_user_spec="debug.log", log_internal_spec="debug-internal.log", log_symlink_user_spec="{wandb_dir}/debug.log", log_symlink_internal_spec="{wandb_dir}/debug-internal.log", resume_fname_spec="{wandb_dir}/wandb-resume.json", files_dir_spec="{wandb_dir}/{run_mode}-{timespec}-{run_id}/files", symlink=None, program=None, notebook_name=None, disable_code=None, ignore_globs=None, save_code=None, program_relpath=None, git_remote=None, dev_prod=None, host=None, username=None, email=None, docker=None, _start_time=None, _start_datetime=None, _cli_only_mode=None, _disable_viewer=None, console=None, disabled=None, reinit=None, _save_requirements=True, show_colors=None, show_emoji=None, silent=None, show_info=None, show_warnings=None, show_errors=None, summary_errors=None, summary_warnings=None, _internal_queue_timeout=2, _internal_check_process=8, _disable_meta=None, _disable_stats=None, _jupyter_path=None, _jupyter_name=None, _jupyter_root=None, _executable=None, _cuda=None, _args=None, _os=None, _python=None, _kaggle=None, _except_exit=None)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_settings.py#L250)

<a name="wandb.sdk.wandb_settings.Settings.resume_fname"></a>
#### resume\_fname

```python
 | @property
 | resume_fname() -> str
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_settings.py#L456)

<a name="wandb.sdk.wandb_settings.Settings.wandb_dir"></a>
#### wandb\_dir

```python
 | @property
 | wandb_dir() -> str
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_settings.py#L460)

<a name="wandb.sdk.wandb_settings.Settings.log_user"></a>
#### log\_user

```python
 | @property
 | log_user() -> str
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_settings.py#L464)

<a name="wandb.sdk.wandb_settings.Settings.log_internal"></a>
#### log\_internal

```python
 | @property
 | log_internal() -> str
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_settings.py#L468)

<a name="wandb.sdk.wandb_settings.Settings.sync_file"></a>
#### sync\_file

```python
 | @property
 | sync_file() -> str
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_settings.py#L476)

<a name="wandb.sdk.wandb_settings.Settings.files_dir"></a>
#### files\_dir

```python
 | @property
 | files_dir() -> str
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_settings.py#L480)

<a name="wandb.sdk.wandb_settings.Settings.log_symlink_user"></a>
#### log\_symlink\_user

```python
 | @property
 | log_symlink_user() -> str
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_settings.py#L484)

<a name="wandb.sdk.wandb_settings.Settings.log_symlink_internal"></a>
#### log\_symlink\_internal

```python
 | @property
 | log_symlink_internal() -> str
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_settings.py#L488)

<a name="wandb.sdk.wandb_settings.Settings.sync_symlink_latest"></a>
#### sync\_symlink\_latest

```python
 | @property
 | sync_symlink_latest() -> str
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_settings.py#L492)

<a name="wandb.sdk.wandb_settings.Settings.settings_system"></a>
#### settings\_system

```python
 | @property
 | settings_system() -> str
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_settings.py#L496)

<a name="wandb.sdk.wandb_settings.Settings.settings_workspace"></a>
#### settings\_workspace

```python
 | @property
 | settings_workspace() -> str
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_settings.py#L500)

<a name="wandb.sdk.wandb_settings.Settings.__copy__"></a>
#### \_\_copy\_\_

```python
 | __copy__()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_settings.py#L656)

Copy (note that the copied object will not be frozen).

<a name="wandb.sdk.wandb_settings.Settings.duplicate"></a>
#### duplicate

```python
 | duplicate()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_settings.py#L662)

<a name="wandb.sdk.wandb_settings.Settings.update"></a>
#### update

```python
 | update(__d=None, **kwargs)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_settings.py#L700)

<a name="wandb.sdk.wandb_settings.Settings.setdefaults"></a>
#### setdefaults

```python
 | setdefaults(__d=None)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_settings.py#L791)

<a name="wandb.sdk.wandb_settings.Settings.save"></a>
#### save

```python
 | save(fname)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_settings.py#L799)

<a name="wandb.sdk.wandb_settings.Settings.load"></a>
#### load

```python
 | load(fname)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_settings.py#L802)

<a name="wandb.sdk.wandb_settings.Settings.__setattr__"></a>
#### \_\_setattr\_\_

```python
 | __setattr__(name, value)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_settings.py#L805)

<a name="wandb.sdk.wandb_settings.Settings.keys"></a>
#### keys

```python
 | keys()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_settings.py#L835)

<a name="wandb.sdk.wandb_settings.Settings.__getitem__"></a>
#### \_\_getitem\_\_

```python
 | __getitem__(k)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_settings.py#L838)

<a name="wandb.sdk.wandb_settings.Settings.freeze"></a>
#### freeze

```python
 | freeze()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_settings.py#L844)

<a name="wandb.sdk.wandb_settings.Settings.is_frozen"></a>
#### is\_frozen

```python
 | is_frozen() -> bool
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_settings.py#L848)

<a name="wandb.sdk.wandb_settings.Settings._Setter"></a>
## \_Setter Objects

```python
class _Setter(object)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_settings.py#L933)

<a name="wandb.sdk.wandb_settings.Settings._Setter.__init__"></a>
#### \_\_init\_\_

```python
 | __init__(settings, source, override)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_settings.py#L934)

<a name="wandb.sdk.wandb_settings.Settings._Setter.__enter__"></a>
#### \_\_enter\_\_

```python
 | __enter__()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_settings.py#L939)

<a name="wandb.sdk.wandb_settings.Settings._Setter.__exit__"></a>
#### \_\_exit\_\_

```python
 | __exit__(exc_type, exc_value, exc_traceback)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_settings.py#L942)

<a name="wandb.sdk.wandb_settings.Settings._Setter.__setattr__"></a>
#### \_\_setattr\_\_

```python
 | __setattr__(name, value)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_settings.py#L945)

<a name="wandb.sdk.wandb_settings.Settings._Setter.update"></a>
#### update

```python
 | update(*args, **kwargs)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_settings.py#L948)

