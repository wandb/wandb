---
menu: main
title: API Documentation
---

<a name="wandb.apis.public"></a>
# wandb.apis.public

[[view_source]](https://github.com/wandb/client-ng/blob/3feea9bf29477622c859e456fc3d6adfc09fdd4c/wandb/apis/public.py#L1)

<a name="wandb.apis.public.Api"></a>
## Api Objects

```python
class Api(object)
```

[[view_source]](https://github.com/wandb/client-ng/blob/3feea9bf29477622c859e456fc3d6adfc09fdd4c/wandb/apis/public.py#L158)

Used for querying the wandb server.

**Examples**:

Most common way to initialize
```
wandb.Api()
```


**Arguments**:

- `overrides` _dict_ - You can set `base_url` if you are using a wandb server
other than https://api.wandb.ai.
You can also set defaults for `entity`, `project`, and `run`.

<a name="wandb.apis.public.Api.flush"></a>
#### flush

```python
 | flush()
```

[[view_source]](https://github.com/wandb/client-ng/blob/3feea9bf29477622c859e456fc3d6adfc09fdd4c/wandb/apis/public.py#L249)

The api object keeps a local cache of runs, so if the state of the run may
change while executing your script you must clear the local cache with `api.flush()`
to get the latest values associated with the run.

<a name="wandb.apis.public.Api.projects"></a>
#### projects

```python
 | projects(entity=None, per_page=200)
```

[[view_source]](https://github.com/wandb/client-ng/blob/3feea9bf29477622c859e456fc3d6adfc09fdd4c/wandb/apis/public.py#L312)

Get projects for a given entity.

**Arguments**:

- `entity` _str_ - Name of the entity requested.  If None will fallback to
default entity passed to `Api`.  If no default entity, will raise a `ValueError`.
- `per_page` _int_ - Sets the page size for query pagination.  None will use the default size.
Usually there is no reason to change this.


**Returns**:

A `Projects` object which is an iterable collection of `Project` objects.

<a name="wandb.apis.public.Api.reports"></a>
#### reports

```python
 | reports(path="", name=None, per_page=50)
```

[[view_source]](https://github.com/wandb/client-ng/blob/3feea9bf29477622c859e456fc3d6adfc09fdd4c/wandb/apis/public.py#L332)

Get reports for a given project path.

WARNING: This api is in beta and will likely change in a future release

**Arguments**:

- `path` _str_ - path to project the report resides in, should be in the form: "entity/project"
- `name` _str_ - optional name of the report requested.
- `per_page` _int_ - Sets the page size for query pagination.  None will use the default size.
Usually there is no reason to change this.


**Returns**:

A `Reports` object which is an iterable collection of `BetaReport` objects.

<a name="wandb.apis.public.Api.runs"></a>
#### runs

```python
 | runs(path="", filters={}, order="-created_at", per_page=50)
```

[[view_source]](https://github.com/wandb/client-ng/blob/3feea9bf29477622c859e456fc3d6adfc09fdd4c/wandb/apis/public.py#L359)

Return a set of runs from a project that match the filters provided.
You can filter by `config.*`, `summary.*`, `state`, `entity`, `createdAt`, etc.

**Examples**:

Find runs in my_project config.experiment_name has been set to "foo"
```
api.runs(path="my_entity/my_project", {"config.experiment_name": "foo"})
```

Find runs in my_project config.experiment_name has been set to "foo" or "bar"
```
api.runs(path="my_entity/my_project",
- `{"$or"` - [{"config.experiment_name": "foo"}, {"config.experiment_name": "bar"}]})
```

Find runs in my_project sorted by ascending loss
```
api.runs(path="my_entity/my_project", {"order": "+summary_metrics.loss"})
```



**Arguments**:

- `path` _str_ - path to project, should be in the form: "entity/project"
- `filters` _dict_ - queries for specific runs using the MongoDB query language.
You can filter by run properties such as config.key, summary_metrics.key, state, entity, createdAt, etc.
For example: {"config.experiment_name": "foo"} would find runs with a config entry
of experiment name set to "foo"
You can compose operations to make more complicated queries,
see Reference for the language is at  https://docs.mongodb.com/manual/reference/operator/query
- `order` _str_ - Order can be `created_at`, `heartbeat_at`, `config.*.value`, or `summary_metrics.*`.
If you prepend order with a + order is ascending.
If you prepend order with a - order is descending (default).
The default order is run.created_at from newest to oldest.


**Returns**:

A `Runs` object, which is an iterable collection of `Run` objects.

<a name="wandb.apis.public.Api.run"></a>
#### run

```python
 | @normalize_exceptions
 | run(path="")
```

[[view_source]](https://github.com/wandb/client-ng/blob/3feea9bf29477622c859e456fc3d6adfc09fdd4c/wandb/apis/public.py#L405)

Returns a single run by parsing path in the form entity/project/run_id.

**Arguments**:

- `path` _str_ - path to run in the form entity/project/run_id.
If api.entity is set, this can be in the form project/run_id
and if api.project is set this can just be the run_id.


**Returns**:

A `Run` object.

<a name="wandb.apis.public.Api.sweep"></a>
#### sweep

```python
 | @normalize_exceptions
 | sweep(path="")
```

[[view_source]](https://github.com/wandb/client-ng/blob/3feea9bf29477622c859e456fc3d6adfc09fdd4c/wandb/apis/public.py#L422)

Returns a sweep by parsing path in the form entity/project/sweep_id.

**Arguments**:

- `path` _str, optional_ - path to sweep in the form entity/project/sweep_id.  If api.entity
is set, this can be in the form project/sweep_id and if api.project is set
this can just be the sweep_id.


**Returns**:

A `Sweep` object.

<a name="wandb.apis.public.Api.artifact"></a>
#### artifact

```python
 | @normalize_exceptions
 | artifact(name, type=None)
```

[[view_source]](https://github.com/wandb/client-ng/blob/3feea9bf29477622c859e456fc3d6adfc09fdd4c/wandb/apis/public.py#L456)

Returns a single artifact by parsing path in the form entity/project/run_id.

**Arguments**:

- `name` _str_ - An artifact name. May be prefixed with entity/project. Valid names
can be in the following forms:
name:version
name:alias
digest
- `type` _str, optional_ - The type of artifact to fetch.

**Returns**:

A `Artifact` object.

<a name="wandb.apis.public.Projects"></a>
## Projects Objects

```python
class Projects(Paginator)
```

[[view_source]](https://github.com/wandb/client-ng/blob/3feea9bf29477622c859e456fc3d6adfc09fdd4c/wandb/apis/public.py#L575)

An iterable collection of `Project` objects.

<a name="wandb.apis.public.Project"></a>
## Project Objects

```python
class Project(Attrs)
```

[[view_source]](https://github.com/wandb/client-ng/blob/3feea9bf29477622c859e456fc3d6adfc09fdd4c/wandb/apis/public.py#L631)

A project is a namespace for runs

<a name="wandb.apis.public.Runs"></a>
## Runs Objects

```python
class Runs(Paginator)
```

[[view_source]](https://github.com/wandb/client-ng/blob/3feea9bf29477622c859e456fc3d6adfc09fdd4c/wandb/apis/public.py#L652)

An iterable collection of runs associated with a project and optional filter.
This is generally used indirectly via the `Api`.runs method

<a name="wandb.apis.public.Run"></a>
## Run Objects

```python
class Run(Attrs)
```

[[view_source]](https://github.com/wandb/client-ng/blob/3feea9bf29477622c859e456fc3d6adfc09fdd4c/wandb/apis/public.py#L737)

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
- `summary` _dict_ - A mutable dict-like property that holds the current summary.
Calling update will persist any changes.
- `project` _str_ - the project associated with the run
- `entity` _str_ - the name of the entity associated with the run
- `user` _str_ - the name of the user who created the run
- `path` _str_ - Unique identifier [entity]/[project]/[run_id]
- `notes` _str_ - Notes about the run
- `read_only` _boolean_ - Whether the run is editable
- `history_keys` _str_ - Keys of the history metrics that have been logged
with `wandb.log({key: value})`

<a name="wandb.apis.public.Run.__init__"></a>
#### \_\_init\_\_

```python
 | __init__(client, entity, project, run_id, attrs={})
```

[[view_source]](https://github.com/wandb/client-ng/blob/3feea9bf29477622c859e456fc3d6adfc09fdd4c/wandb/apis/public.py#L762)

Run is always initialized by calling api.runs() where api is an instance of wandb.Api

<a name="wandb.apis.public.Run.create"></a>
#### create

```python
 | @classmethod
 | create(cls, api, run_id=None, project=None, entity=None)
```

[[view_source]](https://github.com/wandb/client-ng/blob/3feea9bf29477622c859e456fc3d6adfc09fdd4c/wandb/apis/public.py#L820)

Create a run for the given project

<a name="wandb.apis.public.Run.update"></a>
#### update

```python
 | @normalize_exceptions
 | update()
```

[[view_source]](https://github.com/wandb/client-ng/blob/3feea9bf29477622c859e456fc3d6adfc09fdd4c/wandb/apis/public.py#L902)

Persists changes to the run object to the wandb backend.

<a name="wandb.apis.public.Run.files"></a>
#### files

```python
 | @normalize_exceptions
 | files(names=[], per_page=50)
```

[[view_source]](https://github.com/wandb/client-ng/blob/3feea9bf29477622c859e456fc3d6adfc09fdd4c/wandb/apis/public.py#L964)

**Arguments**:

- `names` _list_ - names of the requested files, if empty returns all files
- `per_page` _int_ - number of results per page


**Returns**:

A `Files` object, which is an iterator over `File` obejcts.

<a name="wandb.apis.public.Run.file"></a>
#### file

```python
 | @normalize_exceptions
 | file(name)
```

[[view_source]](https://github.com/wandb/client-ng/blob/3feea9bf29477622c859e456fc3d6adfc09fdd4c/wandb/apis/public.py#L976)

**Arguments**:

- `name` _str_ - name of requested file.


**Returns**:

A `File` matching the name argument.

<a name="wandb.apis.public.Run.history"></a>
#### history

```python
 | @normalize_exceptions
 | history(samples=500, keys=None, x_axis="_step", pandas=True, stream="default")
```

[[view_source]](https://github.com/wandb/client-ng/blob/3feea9bf29477622c859e456fc3d6adfc09fdd4c/wandb/apis/public.py#L987)

Returns sampled history metrics for a run.  This is simpler and faster if you are ok with
the history records being sampled.

**Arguments**:

- `samples` _int, optional_ - The number of samples to return
- `pandas` _bool, optional_ - Return a pandas dataframe
- `keys` _list, optional_ - Only return metrics for specific keys
- `x_axis` _str, optional_ - Use this metric as the xAxis defaults to _step
- `stream` _str, optional_ - "default" for metrics, "system" for machine metrics


**Returns**:

If pandas=True returns a `pandas.DataFrame` of history metrics.
If pandas=False returns a list of dicts of history metrics.

<a name="wandb.apis.public.Run.scan_history"></a>
#### scan\_history

```python
 | @normalize_exceptions
 | scan_history(keys=None, page_size=1000, min_step=None, max_step=None)
```

[[view_source]](https://github.com/wandb/client-ng/blob/3feea9bf29477622c859e456fc3d6adfc09fdd4c/wandb/apis/public.py#L1019)

Returns an iterable collection of all history records for a run.

**Example**:

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

<a name="wandb.apis.public.Sweep"></a>
## Sweep Objects

```python
class Sweep(Attrs)
```

[[view_source]](https://github.com/wandb/client-ng/blob/3feea9bf29477622c859e456fc3d6adfc09fdd4c/wandb/apis/public.py#L1101)

A set of runs associated with a sweep
Instantiate with:
api.sweep(sweep_path)

**Attributes**:

- `runs` _:obj:`Runs`_ - list of runs
- `id` _str_ - sweep id
- `project` _str_ - name of project
- `config` _str_ - dictionary of sweep configuration

<a name="wandb.apis.public.Sweep.best_run"></a>
#### best\_run

```python
 | best_run(order=None)
```

[[view_source]](https://github.com/wandb/client-ng/blob/3feea9bf29477622c859e456fc3d6adfc09fdd4c/wandb/apis/public.py#L1182)

Returns the best run sorted by the metric defined in config or the order passed in

<a name="wandb.apis.public.Sweep.get"></a>
#### get

```python
 | @classmethod
 | get(cls, client, entity=None, project=None, sid=None, withRuns=True, order=None, query=None, **kwargs)
```

[[view_source]](https://github.com/wandb/client-ng/blob/3feea9bf29477622c859e456fc3d6adfc09fdd4c/wandb/apis/public.py#L1203)

Execute a query against the cloud backend

<a name="wandb.apis.public.Files"></a>
## Files Objects

```python
class Files(Paginator)
```

[[view_source]](https://github.com/wandb/client-ng/blob/3feea9bf29477622c859e456fc3d6adfc09fdd4c/wandb/apis/public.py#L1242)

Files is an iterable collection of `File` objects.

<a name="wandb.apis.public.File"></a>
## File Objects

```python
class File(object)
```

[[view_source]](https://github.com/wandb/client-ng/blob/3feea9bf29477622c859e456fc3d6adfc09fdd4c/wandb/apis/public.py#L1298)

File is a class associated with a file saved by wandb.

**Attributes**:

- `name` _string_ - filename
- `url` _string_ - path to file
- `md5` _string_ - md5 of file
- `mimetype` _string_ - mimetype of file
- `updated_at` _string_ - timestamp of last update
- `size` _int_ - size of file in bytes

<a name="wandb.apis.public.File.download"></a>
#### download

```python
 | @normalize_exceptions
 | @retriable(retry_timedelta=datetime.timedelta(
 |         seconds=10),
 |         check_retry_fn=util.no_retry_auth,
 |         retryable_exceptions=(RetryError, requests.RequestException))
 | download(root=".", replace=False)
```

[[view_source]](https://github.com/wandb/client-ng/blob/3feea9bf29477622c859e456fc3d6adfc09fdd4c/wandb/apis/public.py#L1354)

Downloads a file previously saved by a run from the wandb server.

**Arguments**:

- `replace` _boolean_ - If `True`, download will overwrite a local file
if it exists. Defaults to `False`.
- `root` _str_ - Local directory to save the file.  Defaults to ".".


**Raises**:

`ValueError` if file already exists and replace=False

<a name="wandb.apis.public.Reports"></a>
## Reports Objects

```python
class Reports(Paginator)
```

[[view_source]](https://github.com/wandb/client-ng/blob/3feea9bf29477622c859e456fc3d6adfc09fdd4c/wandb/apis/public.py#L1376)

Reports is an iterable collection of `BetaReport` objects.

<a name="wandb.apis.public.QueryGenerator"></a>
## QueryGenerator Objects

```python
class QueryGenerator(object)
```

[[view_source]](https://github.com/wandb/client-ng/blob/3feea9bf29477622c859e456fc3d6adfc09fdd4c/wandb/apis/public.py#L1441)

QueryGenerator is a helper object to write filters for runs

<a name="wandb.apis.public.BetaReport"></a>
## BetaReport Objects

```python
class BetaReport(Attrs)
```

[[view_source]](https://github.com/wandb/client-ng/blob/3feea9bf29477622c859e456fc3d6adfc09fdd4c/wandb/apis/public.py#L1540)

BetaReport is a class associated with reports created in wandb.

WARNING: this API will likely change in a future release

**Attributes**:

- `name` _string_ - report name
- `description` _string_ - report descirpiton;
- `user` _:obj:User_ - the user that created the report
- `spec` _dict_ - the spec off the report;
- `updated_at` _string_ - timestamp of last update

<a name="wandb.apis.public.ArtifactType"></a>
## ArtifactType Objects

```python
class ArtifactType(object)
```

[[view_source]](https://github.com/wandb/client-ng/blob/3feea9bf29477622c859e456fc3d6adfc09fdd4c/wandb/apis/public.py#L1940)

<a name="wandb.apis.public.ArtifactType.collections"></a>
#### collections

```python
 | @normalize_exceptions
 | collections(per_page=50)
```

[[view_source]](https://github.com/wandb/client-ng/blob/3feea9bf29477622c859e456fc3d6adfc09fdd4c/wandb/apis/public.py#L1989)

Artifact collections

<a name="wandb.apis.public.ArtifactCollection"></a>
## ArtifactCollection Objects

```python
class ArtifactCollection(object)
```

[[view_source]](https://github.com/wandb/client-ng/blob/3feea9bf29477622c859e456fc3d6adfc09fdd4c/wandb/apis/public.py#L2000)

<a name="wandb.apis.public.ArtifactCollection.versions"></a>
#### versions

```python
 | @normalize_exceptions
 | versions(per_page=50)
```

[[view_source]](https://github.com/wandb/client-ng/blob/3feea9bf29477622c859e456fc3d6adfc09fdd4c/wandb/apis/public.py#L2014)

Artifact versions

<a name="wandb.apis.public.Artifact"></a>
## Artifact Objects

```python
class Artifact(object)
```

[[view_source]](https://github.com/wandb/client-ng/blob/3feea9bf29477622c859e456fc3d6adfc09fdd4c/wandb/apis/public.py#L2021)

<a name="wandb.apis.public.Artifact.name"></a>
#### name

```python
 | @property
 | name()
```

[[view_source]](https://github.com/wandb/client-ng/blob/3feea9bf29477622c859e456fc3d6adfc09fdd4c/wandb/apis/public.py#L2088)

Stable name you can use to fetch this artifact.

<a name="wandb.apis.public.Artifact.download"></a>
#### download

```python
 | download(root=None)
```

[[view_source]](https://github.com/wandb/client-ng/blob/3feea9bf29477622c859e456fc3d6adfc09fdd4c/wandb/apis/public.py#L2137)

Download the artifact to dir specified by the <root>

**Arguments**:

- `root` _str, optional_ - directory to download artifact to. If None
artifact will be downloaded to './artifacts/<self.name>/'


**Returns**:

The path to the downloaded contents.

<a name="wandb.apis.public.Artifact.file"></a>
#### file

```python
 | file(root=None)
```

[[view_source]](https://github.com/wandb/client-ng/blob/3feea9bf29477622c859e456fc3d6adfc09fdd4c/wandb/apis/public.py#L2178)

Download a single file artifact to dir specified by the <root>

**Arguments**:

- `root` _str, optional_ - directory to download artifact to. If None
artifact will be downloaded to './artifacts/<self.name>/'


**Returns**:

The full path of the downloaded file

<a name="wandb.apis.public.Artifact.save"></a>
#### save

```python
 | @normalize_exceptions
 | save()
```

[[view_source]](https://github.com/wandb/client-ng/blob/3feea9bf29477622c859e456fc3d6adfc09fdd4c/wandb/apis/public.py#L2218)

Persists artifact changes to the wandb backend.

<a name="wandb.apis.public.Artifact.verify"></a>
#### verify

```python
 | verify(root=None)
```

[[view_source]](https://github.com/wandb/client-ng/blob/3feea9bf29477622c859e456fc3d6adfc09fdd4c/wandb/apis/public.py#L2250)

Verify an artifact by checksumming its downloaded contents.

Raises a ValueError if the verification fails. Does not verify downloaded
reference files.

**Arguments**:

- `root` _str, optional_ - directory to download artifact to. If None
artifact will be downloaded to './artifacts/<self.name>/'

<a name="wandb.apis.public.ArtifactVersions"></a>
## ArtifactVersions Objects

```python
class ArtifactVersions(Paginator)
```

[[view_source]](https://github.com/wandb/client-ng/blob/3feea9bf29477622c859e456fc3d6adfc09fdd4c/wandb/apis/public.py#L2338)

An iterable collection of artifact versions associated with a project and optional filter.
This is generally used indirectly via the `Api`.artifact_versions method

