---
description: wandb.apis.public
---

# wandb.apis.public
[source](https://github.com/wandb/client/blob/feature/docs/wandb/apis/public.py#L0)


## Api
[source](https://github.com/wandb/client/blob/feature/docs/wandb/apis/public.py#L90)
```python
Api(self, overrides={})
```

Used for querying the wandb server.

**Examples**:

 Most common way to initialize
```python
wandb.Api()
```
 

**Arguments**:

- `overrides` _dict_ - You can set `base_url` if you are using a wandb server other than https://api.wandb.ai. You can also set defaults for `entity`, `project`, and `run`.
 

### Api.flush
[source](https://github.com/wandb/client/blob/feature/docs/wandb/apis/public.py#L157)
```python
Api.flush(self)
```

The api object keeps a local cache of runs, so if the state of the run may change while executing your script you must clear the local cache with `api.flush()` to get the latest values associated with the run.

### Api.projects
[source](https://github.com/wandb/client/blob/feature/docs/wandb/apis/public.py#L192)
```python
Api.projects(self, entity=None, per_page=None)
```
Get projects for a given entity.

**Arguments**:

- `entity` _str_ - Name of the entity requested.  If None will fallback to default entity passed to [`Api`.](#api`.)  If no default entity, will raise a `ValueError`.
- `per_page` _int_ - Sets the page size for query pagination.  None will use the default size. Usually there is no reason to change this.
 

**Returns**:

 A [`Projects`](#projects) object which is an iterable collection of [`Project`](#project) objects.
 
 

### Api.runs
[source](https://github.com/wandb/client/blob/feature/docs/wandb/apis/public.py#L212)
```python
Api.runs(self, path='', filters={}, order='-created_at', per_page=None)
```
Return a set of runs from a project that match the filters provided. You can filter by `config.*`, `summary.*`, `state`, `entity`, `createdAt`, etc.

**Examples**:

 Find runs in my_project config.experiment_name has been set to "foo"
```python
api.runs(path="my_entity/my_project", {"config.experiment_name": "foo"})
```
 
 Find runs in my_project config.experiment_name has been set to "foo" or "bar"
```python
api.runs(path="my_entity/my_project",
{"$or": [{"config.experiment_name": "foo"}, {"config.experiment_name": "bar"}]})
```
 
 Find runs in my_project sorted by ascending loss
```python
api.runs(path="my_entity/my_project", {"order": "+summary.loss"})
```
 
 

**Arguments**:

- `path` _str_ - path to project, should be in the form: "entity/project"
- `filters` _dict_ - queries for specific runs using the MongoDB query language. You can filter by run properties such as config.key, summary.key, state, entity, createdAt, etc. For example: {"config.experiment_name": "foo"} would find runs with a config entry of experiment name set to "foo" You can compose operations to make more complicated queries, see Reference for the language is at  https://docs.mongodb.com/manual/reference/operator/query
- `order` _str_ - Order can be `created_at`, `heartbeat_at`, `config.*.value`, or `summary.*`. If you prepend order with a + order is ascending. If you prepend order with a - order is descending (default). The default order is run.created_at from newest to oldest.
 

**Returns**:

 A [`Runs`](#runs) object, which is an iterable collection of [`Run`](#run) objects.
 

### Api.run
[source](https://github.com/wandb/client/blob/feature/docs/wandb/apis/public.py#L256)
```python
Api.run(self, path='')
```
Returns a single run by parsing path in the form entity/project/run_id.

**Arguments**:

- `path` _str_ - path to run in the form entity/project/run_id. If api.entity is set, this can be in the form project/run_id and if api.project is set this can just be the run_id.
 

**Returns**:

 A [`Run`](#run) object.
 

### Api.sweep
[source](https://github.com/wandb/client/blob/feature/docs/wandb/apis/public.py#L273)
```python
Api.sweep(self, path='')
```

Returns a sweep by parsing path in the form entity/project/sweep_id.

**Arguments**:

- `path` _str, optional_ - path to sweep in the form entity/project/sweep_id.  If api.entity is set, this can be in the form project/sweep_id and if api.project is set this can just be the sweep_id.
 

**Returns**:

 A [`Sweep`](#sweep) object.
 

## Projects
[source](https://github.com/wandb/client/blob/feature/docs/wandb/apis/public.py#L384)
```python
Projects(self, client, entity, per_page=50)
```

An iterable collection of [`Project`](#project) objects.


## Project
[source](https://github.com/wandb/client/blob/feature/docs/wandb/apis/public.py#L438)
```python
Project(self, entity, project, attrs)
```
A project is a namespace for runs

## Runs
[source](https://github.com/wandb/client/blob/feature/docs/wandb/apis/public.py#L449)
```python
Runs(self, client, entity, project, filters={}, order=None, per_page=50)
```
An iterable collection of runs associated with a project and optional filter.


## Run
[source](https://github.com/wandb/client/blob/feature/docs/wandb/apis/public.py#L515)
```python
Run(self, client, entity, project, run_id, attrs={})
```

A single run associated with an entity and project.

**Attributes**:

- `tags` _[str]_ - a list of tags associated with the run
- `url` _str_ - the url of this run
- `id` _str_ - unique identifier for the run (defaults to eight characters)
- `name` _str_ - the name of the run
- `state` _str_ - one of: running, finished, crashed, aborted
- `config` _dict_ - a dict of hyperparameters associated with the run
- `created_at` _str_ - ISO timestamp when the run was started
- `system_metrics` _dict_ - the latest system metrics recorded for the run
- `summary` _dict_ - A mutable dict-like property that holds the current summary. Calling update will persist any changes.
- `project` _str_ - the project associated with the run
- `entity` _str_ - the name of the entity associated with the run
- `user` _str_ - the name of the user who created the run
- `path` _str_ - Unique identifier [entity]/[project]/[run_id]
- `notes` _str_ - Notes about the run
- `read_only` _boolean_ - Whether the run is editable
- `history_keys` _str_ - Keys of the history metrics that have been logged with `wandb.log({key: value})`
 

### Run.create
[source](https://github.com/wandb/client/blob/feature/docs/wandb/apis/public.py#L596)
```python
Run.create(api, run_id=None, project=None, entity=None)
```
Create a run for the given project

### Run.update
[source](https://github.com/wandb/client/blob/feature/docs/wandb/apis/public.py#L663)
```python
Run.update(self)
```

Persists changes to the run object to the wandb backend.


### Run.files
[source](https://github.com/wandb/client/blob/feature/docs/wandb/apis/public.py#L723)
```python
Run.files(self, names=[], per_page=50)
```

**Arguments**:

- `names` _list_ - names of the requested files, if empty returns all files
- `per_page` _int_ - number of results per page
 

**Returns**:

 A [`Files`](#files) object, which is an iterator over [`File`](#file) obejcts.
 

### Run.file
[source](https://github.com/wandb/client/blob/feature/docs/wandb/apis/public.py#L735)
```python
Run.file(self, name)
```

**Arguments**:

- `name` _str_ - name of requested file.
 

**Returns**:

 A [`File`](#file) matching the name argument.
 

### Run.history
[source](https://github.com/wandb/client/blob/feature/docs/wandb/apis/public.py#L746)
```python
Run.history(self,
            samples=500,
            keys=None,
            x_axis='_step',
            pandas=True,
            stream='default')
```

Returns sampled history metrics for a run.  This is simpler and faster if you are ok with the history records being sampled.

**Arguments**:

- `samples` _int, optional_ - The number of samples to return
- `pandas` _bool, optional_ - Return a pandas dataframe
- `keys` _list, optional_ - Only return metrics for specific keys
- `x_axis` _str, optional_ - Use this metric as the xAxis defaults to _step
- `stream` _str, optional_ - "default" for metrics, "system" for machine metrics
 

**Returns**:

 If pandas=True returns a `pandas.DataFrame` of history metrics. If pandas=False returns a list of dicts of history metrics.
 

### Run.scan_history
[source](https://github.com/wandb/client/blob/feature/docs/wandb/apis/public.py#L778)
```python
Run.scan_history(self, keys=None, page_size=1000)
```

Returns an iterable collection of all history records for a run.

**Examples**:

 Export all the loss values for an example run
 
```python
run = api.run("l2k2/examples-numpy-boston/i0wt6xua")
history = run.scan_history(keys=["Loss"])
losses = [row["Loss"] for row in history]
```
 
 

**Arguments**:

- `keys` _[str], optional_ - only fetch these keys, and only fetch rows that have all of keys defined.
- `page_size` _int, optional_ - size of pages to fetch from the api
 

**Returns**:

 An iterable collection over history records (dict).
 

## Sweep
[source](https://github.com/wandb/client/blob/feature/docs/wandb/apis/public.py#L831)
```python
Sweep(self, client, entity, project, sweep_id, attrs={})
```
A set of runs associated with a sweep Instantiate with: api.sweep(sweep_path)

**Attributes**:

- `runs` _[`Runs`](#runs)_ - list of runs
- `id` _str_ - sweep id
- `project` _str_ - name of project
- `config` _str_ - dictionary of sweep configuration
 

## Files
[source](https://github.com/wandb/client/blob/feature/docs/wandb/apis/public.py#L914)
```python
Files(self, client, run, names=[], per_page=50, upload=False)
```
Files is an iterable collection of [`File`](#file) objects.

## File
[source](https://github.com/wandb/client/blob/feature/docs/wandb/apis/public.py#L970)
```python
File(self, client, attrs)
```
File is a class associated with a file saved by wandb.

**Attributes**:

- `name` _string_ - filename
- `url` _string_ - path to file
- `md5` _string_ - md5 of file
- `mimetype` _string_ - mimetype of file
- `updated_at` _string_ - timestamp of last update
- `size` _int_ - size of file in bytes
 
 

### File.download
[source](https://github.com/wandb/client/blob/feature/docs/wandb/apis/public.py#L1014)
```python
File.download(self, replace=False, root='.')
```
Downloads a file previously saved by a run from the wandb server.

**Arguments**:

- `replace` _boolean_ - If `True`, download will overwrite a local file if it exists. Defaults to `False`.
- `root` _str_ - Local directory to save the file.  Defaults to ".".
 

**Raises**:

 `ValueError` if file already exists and replace=False
 
