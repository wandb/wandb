
# [wandb.apis.public](https://github.com/wandb/client/blob/feature/docs/wandb/apis/public.py#L0)


## [Api](https://github.com/wandb/client/blob/feature/docs/wandb/apis/public.py#L90)
```python
Api(self, overrides={})
```
W&B Public API
Used for querying the wandb server.
Initialize with wandb.Api()

**Arguments**:

- `overrides` _`dict`_ - You can set defaults such as
  entity, project, and run here as well as which api server to use.
  

## [Projects](https://github.com/wandb/client/blob/feature/docs/wandb/apis/public.py#L321)
```python
Projects(self, client, entity, per_page=50)
```
An iterable set of projects

## [Project](https://github.com/wandb/client/blob/feature/docs/wandb/apis/public.py#L373)
```python
Project(self, entity, project, attrs)
```
A project is a namespace for runs

## [Runs](https://github.com/wandb/client/blob/feature/docs/wandb/apis/public.py#L384)
```python
Runs(self, client, entity, project, filters={}, order=None, per_page=50)
```
An iterable set of runs associated with a project and optional filter.


## [Run](https://github.com/wandb/client/blob/feature/docs/wandb/apis/public.py#L450)
```python
Run(self, client, entity, project, run_id, attrs={})
```

A single run associated with a user and project

**Attributes**:

  tags (list(str)): a list of tags associated with the run
- `url` _str_ - the url of this run
- `id` _str_ - unique identifier for the run
- `name` _str_ - the name of the run
- `state` _str_ - one of: running, finished, crashed, aborted
- `config` _dict_ - a dict of hyperparameters associated with the run
- `created_at` _str_ - ISO timestamp when the run was started
- `system_metrics` _dict_ - the latest system metrics recorded for the run
- `summary` _dict_ - A mutable dict-like property that holds the current summary.
  Calling update will persist any changes.
- `project` _str_ - the project associated with the run
- `entity` _str_ - the entity associated with the run
- `user` _str_ - the User who created the run
- `path` _str_ - Unique identifier [entity]/[project]/[run_id]
- `notes` _str_ - Notes about the run
- `read_only` _boolean_ - Is the run editable
- `history_keys` _str_ - Metrics that have been logged with wandb.log()
  

## [Sweep](https://github.com/wandb/client/blob/feature/docs/wandb/apis/public.py#L745)
```python
Sweep(self, client, entity, project, sweep_id, attrs={})
```
A set of runs associated with a sweep
Instantiate with:
api.sweep(sweep_path)

**Attributes**:

- `runs` _Runs_ - list of runs
- `id` _string_ - sweep id
- `project` _string_ - name of project
- `config` _string_ - dictionary of sweep configuration
  

## [Files](https://github.com/wandb/client/blob/feature/docs/wandb/apis/public.py#L828)
```python
Files(self, client, run, names=[], per_page=50, upload=False)
```
Files is a paginated list of files.

## [File](https://github.com/wandb/client/blob/feature/docs/wandb/apis/public.py#L884)
```python
File(self, client, attrs)
```
File is a file saved by wandb.
