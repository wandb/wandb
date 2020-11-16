---
title: API Documentation
---

<a name="wandb.apis.public"></a>
# wandb.apis.public

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L1)

<a name="wandb.apis.public.PY3"></a>
#### PY3

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L31)

<a name="wandb.apis.public.logger"></a>
#### logger

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L37)

<a name="wandb.apis.public.RETRY_TIMEDELTA"></a>
#### RETRY\_TIMEDELTA

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L40)

<a name="wandb.apis.public.WANDB_INTERNAL_KEYS"></a>
#### WANDB\_INTERNAL\_KEYS

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L41)

<a name="wandb.apis.public.PROJECT_FRAGMENT"></a>
#### PROJECT\_FRAGMENT

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L42)

<a name="wandb.apis.public.RUN_FRAGMENT"></a>
#### RUN\_FRAGMENT

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L50)

<a name="wandb.apis.public.FILE_FRAGMENT"></a>
#### FILE\_FRAGMENT

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L74)

<a name="wandb.apis.public.ARTIFACTS_TYPES_FRAGMENT"></a>
#### ARTIFACTS\_TYPES\_FRAGMENT

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L95)

<a name="wandb.apis.public.ARTIFACT_FRAGMENT"></a>
#### ARTIFACT\_FRAGMENT

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L113)

<a name="wandb.apis.public.ARTIFACT_FILES_FRAGMENT"></a>
#### ARTIFACT\_FILES\_FRAGMENT

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L141)

<a name="wandb.apis.public.RetryingClient"></a>
## RetryingClient Objects

```python
class RetryingClient(object)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L164)

<a name="wandb.apis.public.RetryingClient.__init__"></a>
#### \_\_init\_\_

```python
 | __init__(client)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L165)

<a name="wandb.apis.public.RetryingClient.app_url"></a>
#### app\_url

```python
 | @property
 | app_url()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L169)

<a name="wandb.apis.public.RetryingClient.execute"></a>
#### execute

```python
 | @retriable(
 |         retry_timedelta=RETRY_TIMEDELTA,
 |         check_retry_fn=util.no_retry_auth,
 |         retryable_exceptions=(RetryError, requests.RequestException),
 |     )
 | execute(*args, **kwargs)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L177)

<a name="wandb.apis.public.Api"></a>
## Api Objects

```python
class Api(object)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L181)

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

<a name="wandb.apis.public.Api.VIEWER_QUERY"></a>
#### VIEWER\_QUERY

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L198)

<a name="wandb.apis.public.Api.__init__"></a>
#### \_\_init\_\_

```python
 | __init__(overrides={})
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L217)

<a name="wandb.apis.public.Api.create_run"></a>
#### create\_run

```python
 | create_run(**kwargs)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L245)

<a name="wandb.apis.public.Api.client"></a>
#### client

```python
 | @property
 | client()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L251)

<a name="wandb.apis.public.Api.user_agent"></a>
#### user\_agent

```python
 | @property
 | user_agent()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L255)

<a name="wandb.apis.public.Api.api_key"></a>
#### api\_key

```python
 | @property
 | api_key()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L259)

<a name="wandb.apis.public.Api.default_entity"></a>
#### default\_entity

```python
 | @property
 | default_entity()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L270)

<a name="wandb.apis.public.Api.flush"></a>
#### flush

```python
 | flush()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L276)

The api object keeps a local cache of runs, so if the state of the run may
change while executing your script you must clear the local cache with `api.flush()`
to get the latest values associated with the run.

<a name="wandb.apis.public.Api.projects"></a>
#### projects

```python
 | projects(entity=None, per_page=200)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L338)

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

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L360)

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

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L393)

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

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L445)

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

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L462)

Returns a sweep by parsing path in the form entity/project/sweep_id.

**Arguments**:

- `path` _str, optional_ - path to sweep in the form entity/project/sweep_id.  If api.entity
is set, this can be in the form project/sweep_id and if api.project is set
this can just be the sweep_id.


**Returns**:

A `Sweep` object.

<a name="wandb.apis.public.Api.artifact_types"></a>
#### artifact\_types

```python
 | @normalize_exceptions
 | artifact_types(project=None)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L480)

<a name="wandb.apis.public.Api.artifact_type"></a>
#### artifact\_type

```python
 | @normalize_exceptions
 | artifact_type(type_name, project=None)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L485)

<a name="wandb.apis.public.Api.artifact_versions"></a>
#### artifact\_versions

```python
 | @normalize_exceptions
 | artifact_versions(type_name, name, per_page=50)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L490)

<a name="wandb.apis.public.Api.artifact"></a>
#### artifact

```python
 | @normalize_exceptions
 | artifact(name, type=None)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L496)

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

<a name="wandb.apis.public.Api.artifact_from_id"></a>
#### artifact\_from\_id

```python
 | artifact_from_id(id)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L517)

<a name="wandb.apis.public.Attrs"></a>
## Attrs Objects

```python
class Attrs(object)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L521)

<a name="wandb.apis.public.Attrs.__init__"></a>
#### \_\_init\_\_

```python
 | __init__(attrs)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L522)

<a name="wandb.apis.public.Attrs.snake_to_camel"></a>
#### snake\_to\_camel

```python
 | snake_to_camel(string)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L525)

<a name="wandb.apis.public.Attrs.__getattr__"></a>
#### \_\_getattr\_\_

```python
 | __getattr__(name)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L529)

<a name="wandb.apis.public.Paginator"></a>
## Paginator Objects

```python
class Paginator(object)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L543)

<a name="wandb.apis.public.Paginator.QUERY"></a>
#### QUERY

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L544)

<a name="wandb.apis.public.Paginator.__init__"></a>
#### \_\_init\_\_

```python
 | __init__(client, variables, per_page=None)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L546)

<a name="wandb.apis.public.Paginator.__iter__"></a>
#### \_\_iter\_\_

```python
 | __iter__()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L557)

<a name="wandb.apis.public.Paginator.__len__"></a>
#### \_\_len\_\_

```python
 | __len__()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L561)

<a name="wandb.apis.public.Paginator.length"></a>
#### length

```python
 | @property
 | length()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L569)

<a name="wandb.apis.public.Paginator.more"></a>
#### more

```python
 | @property
 | more()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L573)

<a name="wandb.apis.public.Paginator.cursor"></a>
#### cursor

```python
 | @property
 | cursor()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L577)

<a name="wandb.apis.public.Paginator.convert_objects"></a>
#### convert\_objects

```python
 | convert_objects()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L580)

<a name="wandb.apis.public.Paginator.update_variables"></a>
#### update\_variables

```python
 | update_variables()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L583)

<a name="wandb.apis.public.Paginator.__getitem__"></a>
#### \_\_getitem\_\_

```python
 | __getitem__(index)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L596)

<a name="wandb.apis.public.Paginator.__next__"></a>
#### \_\_next\_\_

```python
 | __next__()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L602)

<a name="wandb.apis.public.Paginator.next"></a>
#### next

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L611)

<a name="wandb.apis.public.User"></a>
## User Objects

```python
class User(Attrs)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L614)

<a name="wandb.apis.public.User.init"></a>
#### init

```python
 | init(attrs)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L615)

<a name="wandb.apis.public.Projects"></a>
## Projects Objects

```python
class Projects(Paginator)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L619)

An iterable collection of `Project` objects.

<a name="wandb.apis.public.Projects.QUERY"></a>
#### QUERY

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L624)

<a name="wandb.apis.public.Projects.__init__"></a>
#### \_\_init\_\_

```python
 | __init__(client, entity, per_page=50)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L645)

<a name="wandb.apis.public.Projects.length"></a>
#### length

```python
 | @property
 | length()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L654)

<a name="wandb.apis.public.Projects.more"></a>
#### more

```python
 | @property
 | more()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L658)

<a name="wandb.apis.public.Projects.cursor"></a>
#### cursor

```python
 | @property
 | cursor()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L665)

<a name="wandb.apis.public.Projects.convert_objects"></a>
#### convert\_objects

```python
 | convert_objects()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L671)

<a name="wandb.apis.public.Projects.__repr__"></a>
#### \_\_repr\_\_

```python
 | __repr__()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L677)

<a name="wandb.apis.public.Project"></a>
## Project Objects

```python
class Project(Attrs)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L681)

A project is a namespace for runs

<a name="wandb.apis.public.Project.__init__"></a>
#### \_\_init\_\_

```python
 | __init__(client, entity, project, attrs)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L684)

<a name="wandb.apis.public.Project.path"></a>
#### path

```python
 | @property
 | path()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L691)

<a name="wandb.apis.public.Project.__repr__"></a>
#### \_\_repr\_\_

```python
 | __repr__()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L694)

<a name="wandb.apis.public.Project.artifacts_types"></a>
#### artifacts\_types

```python
 | @normalize_exceptions
 | artifacts_types(per_page=50)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L698)

<a name="wandb.apis.public.Runs"></a>
## Runs Objects

```python
class Runs(Paginator)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L702)

An iterable collection of runs associated with a project and optional filter.
This is generally used indirectly via the `Api`.runs method

<a name="wandb.apis.public.Runs.QUERY"></a>
#### QUERY

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L707)

<a name="wandb.apis.public.Runs.__init__"></a>
#### \_\_init\_\_

```python
 | __init__(client, entity, project, filters={}, order=None, per_page=50)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L732)

<a name="wandb.apis.public.Runs.length"></a>
#### length

```python
 | @property
 | length()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L747)

<a name="wandb.apis.public.Runs.more"></a>
#### more

```python
 | @property
 | more()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L754)

<a name="wandb.apis.public.Runs.cursor"></a>
#### cursor

```python
 | @property
 | cursor()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L761)

<a name="wandb.apis.public.Runs.convert_objects"></a>
#### convert\_objects

```python
 | convert_objects()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L767)

<a name="wandb.apis.public.Runs.__repr__"></a>
#### \_\_repr\_\_

```python
 | __repr__()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L803)

<a name="wandb.apis.public.Run"></a>
## Run Objects

```python
class Run(Attrs)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L807)

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

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L832)

Run is always initialized by calling api.runs() where api is an instance of wandb.Api

<a name="wandb.apis.public.Run.entity"></a>
#### entity

```python
 | @property
 | entity()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L855)

<a name="wandb.apis.public.Run.username"></a>
#### username

```python
 | @property
 | username()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L859)

<a name="wandb.apis.public.Run.storage_id"></a>
#### storage\_id

```python
 | @property
 | storage_id()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L864)

<a name="wandb.apis.public.Run.id"></a>
#### id

```python
 | @property
 | id()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L871)

<a name="wandb.apis.public.Run.id"></a>
#### id

```python
 | @id.setter
 | id(new_id)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L875)

<a name="wandb.apis.public.Run.name"></a>
#### name

```python
 | @property
 | name()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L881)

<a name="wandb.apis.public.Run.name"></a>
#### name

```python
 | @name.setter
 | name(new_name)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L885)

<a name="wandb.apis.public.Run.create"></a>
#### create

```python
 | @classmethod
 | create(cls, api, run_id=None, project=None, entity=None)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L890)

Create a run for the given project

<a name="wandb.apis.public.Run.load"></a>
#### load

```python
 | load(force=False)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L931)

<a name="wandb.apis.public.Run.update"></a>
#### update

```python
 | @normalize_exceptions
 | update()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L996)

Persists changes to the run object to the wandb backend.

<a name="wandb.apis.public.Run.save"></a>
#### save

```python
 | save()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L1024)

<a name="wandb.apis.public.Run.json_config"></a>
#### json\_config

```python
 | @property
 | json_config()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L1028)

<a name="wandb.apis.public.Run.files"></a>
#### files

```python
 | @normalize_exceptions
 | files(names=[], per_page=50)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L1073)

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

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L1085)

**Arguments**:

- `name` _str_ - name of requested file.


**Returns**:

A `File` matching the name argument.

<a name="wandb.apis.public.Run.upload_file"></a>
#### upload\_file

```python
 | @normalize_exceptions
 | upload_file(path, root=".")
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L1096)

**Arguments**:

- `path` _str_ - name of file to upload.
- `root` _str_ - the root path to save the file relative to.  i.e.
If you want to have the file saved in the run as "my_dir/file.txt"
and you're currently in "my_dir" you would set root to "../"


**Returns**:

A `File` matching the name argument.

<a name="wandb.apis.public.Run.history"></a>
#### history

```python
 | @normalize_exceptions
 | history(samples=500, keys=None, x_axis="_step", pandas=True, stream="default")
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L1119)

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

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L1153)

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

<a name="wandb.apis.public.Run.logged_artifacts"></a>
#### logged\_artifacts

```python
 | @normalize_exceptions
 | logged_artifacts(per_page=100)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L1202)

<a name="wandb.apis.public.Run.used_artifacts"></a>
#### used\_artifacts

```python
 | @normalize_exceptions
 | used_artifacts(per_page=100)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L1206)

<a name="wandb.apis.public.Run.use_artifact"></a>
#### use\_artifact

```python
 | @normalize_exceptions
 | use_artifact(artifact)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L1210)

Declare an artifact as an input to a run.

**Arguments**:

- `artifact` _`Artifact`_ - An artifact returned from
`wandb.Api().artifact(name)`

**Returns**:

A `Artifact` object.

<a name="wandb.apis.public.Run.log_artifact"></a>
#### log\_artifact

```python
 | @normalize_exceptions
 | log_artifact(artifact, aliases=None)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L1237)

Declare an artifact as output of a run.

**Arguments**:

- `artifact` _`Artifact`_ - An artifact returned from
`wandb.Api().artifact(name)`
- `aliases` _list, optional_ - Aliases to apply to this artifact

**Returns**:

A `Artifact` object.

<a name="wandb.apis.public.Run.summary"></a>
#### summary

```python
 | @property
 | summary()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L1271)

<a name="wandb.apis.public.Run.path"></a>
#### path

```python
 | @property
 | path()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L1278)

<a name="wandb.apis.public.Run.url"></a>
#### url

```python
 | @property
 | url()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L1286)

<a name="wandb.apis.public.Run.lastHistoryStep"></a>
#### lastHistoryStep

```python
 | @property
 | lastHistoryStep()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L1292)

<a name="wandb.apis.public.Run.__repr__"></a>
#### \_\_repr\_\_

```python
 | __repr__()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L1313)

<a name="wandb.apis.public.Sweep"></a>
## Sweep Objects

```python
class Sweep(Attrs)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L1317)

A set of runs associated with a sweep
Instantiate with:
api.sweep(sweep_path)

**Attributes**:

- `runs` _`Runs`_ - list of runs
- `id` _str_ - sweep id
- `project` _str_ - name of project
- `config` _str_ - dictionary of sweep configuration

<a name="wandb.apis.public.Sweep.QUERY"></a>
#### QUERY

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L1329)

<a name="wandb.apis.public.Sweep.__init__"></a>
#### \_\_init\_\_

```python
 | __init__(client, entity, project, sweep_id, attrs={})
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L1358)

<a name="wandb.apis.public.Sweep.entity"></a>
#### entity

```python
 | @property
 | entity()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L1371)

<a name="wandb.apis.public.Sweep.username"></a>
#### username

```python
 | @property
 | username()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L1375)

<a name="wandb.apis.public.Sweep.config"></a>
#### config

```python
 | @property
 | config()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L1380)

<a name="wandb.apis.public.Sweep.load"></a>
#### load

```python
 | load(force=False)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L1383)

<a name="wandb.apis.public.Sweep.order"></a>
#### order

```python
 | @property
 | order()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L1395)

<a name="wandb.apis.public.Sweep.best_run"></a>
#### best\_run

```python
 | best_run(order=None)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L1403)

Returns the best run sorted by the metric defined in config or the order passed in

<a name="wandb.apis.public.Sweep.path"></a>
#### path

```python
 | @property
 | path()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L1429)

<a name="wandb.apis.public.Sweep.url"></a>
#### url

```python
 | @property
 | url()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L1437)

<a name="wandb.apis.public.Sweep.get"></a>
#### get

```python
 | @classmethod
 | get(cls, client, entity=None, project=None, sid=None, withRuns=True, order=None, query=None, **kwargs)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L1443)

Execute a query against the cloud backend

<a name="wandb.apis.public.Sweep.__repr__"></a>
#### \_\_repr\_\_

```python
 | __repr__()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L1494)

<a name="wandb.apis.public.Files"></a>
## Files Objects

```python
class Files(Paginator)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L1498)

Files is an iterable collection of `File` objects.

<a name="wandb.apis.public.Files.QUERY"></a>
#### QUERY

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L1501)

<a name="wandb.apis.public.Files.__init__"></a>
#### \_\_init\_\_

```python
 | __init__(client, run, names=[], per_page=50, upload=False)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L1517)

<a name="wandb.apis.public.Files.length"></a>
#### length

```python
 | @property
 | length()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L1529)

<a name="wandb.apis.public.Files.more"></a>
#### more

```python
 | @property
 | more()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L1536)

<a name="wandb.apis.public.Files.cursor"></a>
#### cursor

```python
 | @property
 | cursor()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L1545)

<a name="wandb.apis.public.Files.update_variables"></a>
#### update\_variables

```python
 | update_variables()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L1551)

<a name="wandb.apis.public.Files.convert_objects"></a>
#### convert\_objects

```python
 | convert_objects()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L1554)

<a name="wandb.apis.public.Files.__repr__"></a>
#### \_\_repr\_\_

```python
 | __repr__()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L1560)

<a name="wandb.apis.public.File"></a>
## File Objects

```python
class File(object)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L1564)

File is a class associated with a file saved by wandb.

**Attributes**:

- `name` _string_ - filename
- `url` _string_ - path to file
- `md5` _string_ - md5 of file
- `mimetype` _string_ - mimetype of file
- `updated_at` _string_ - timestamp of last update
- `size` _int_ - size of file in bytes

<a name="wandb.apis.public.File.__init__"></a>
#### \_\_init\_\_

```python
 | __init__(client, attrs)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L1577)

<a name="wandb.apis.public.File.name"></a>
#### name

```python
 | @property
 | name()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L1585)

<a name="wandb.apis.public.File.url"></a>
#### url

```python
 | @property
 | url()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L1589)

<a name="wandb.apis.public.File.md5"></a>
#### md5

```python
 | @property
 | md5()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L1593)

<a name="wandb.apis.public.File.digest"></a>
#### digest

```python
 | @property
 | digest()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L1597)

<a name="wandb.apis.public.File.mimetype"></a>
#### mimetype

```python
 | @property
 | mimetype()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L1601)

<a name="wandb.apis.public.File.updated_at"></a>
#### updated\_at

```python
 | @property
 | updated_at()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L1605)

<a name="wandb.apis.public.File.size"></a>
#### size

```python
 | @property
 | size()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L1609)

<a name="wandb.apis.public.File.download"></a>
#### download

```python
 | @normalize_exceptions
 | @retriable(
 |         retry_timedelta=RETRY_TIMEDELTA,
 |         check_retry_fn=util.no_retry_auth,
 |         retryable_exceptions=(RetryError, requests.RequestException),
 |     )
 | download(root=".", replace=False)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L1621)

Downloads a file previously saved by a run from the wandb server.

**Arguments**:

- `replace` _boolean_ - If `True`, download will overwrite a local file
if it exists. Defaults to `False`.
- `root` _str_ - Local directory to save the file.  Defaults to ".".


**Raises**:

`ValueError` if file already exists and replace=False

<a name="wandb.apis.public.File.__repr__"></a>
#### \_\_repr\_\_

```python
 | __repr__()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L1638)

<a name="wandb.apis.public.Reports"></a>
## Reports Objects

```python
class Reports(Paginator)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L1644)

Reports is an iterable collection of `BetaReport` objects.

<a name="wandb.apis.public.Reports.QUERY"></a>
#### QUERY

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L1647)

<a name="wandb.apis.public.Reports.__init__"></a>
#### \_\_init\_\_

```python
 | __init__(client, project, name=None, entity=None, per_page=50)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L1673)

<a name="wandb.apis.public.Reports.length"></a>
#### length

```python
 | @property
 | length()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L1684)

<a name="wandb.apis.public.Reports.more"></a>
#### more

```python
 | @property
 | more()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L1689)

<a name="wandb.apis.public.Reports.cursor"></a>
#### cursor

```python
 | @property
 | cursor()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L1698)

<a name="wandb.apis.public.Reports.update_variables"></a>
#### update\_variables

```python
 | update_variables()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L1704)

<a name="wandb.apis.public.Reports.convert_objects"></a>
#### convert\_objects

```python
 | convert_objects()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L1709)

<a name="wandb.apis.public.Reports.__repr__"></a>
#### \_\_repr\_\_

```python
 | __repr__()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L1720)

<a name="wandb.apis.public.QueryGenerator"></a>
## QueryGenerator Objects

```python
class QueryGenerator(object)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L1724)

QueryGenerator is a helper object to write filters for runs

<a name="wandb.apis.public.QueryGenerator.INDIVIDUAL_OP_TO_MONGO"></a>
#### INDIVIDUAL\_OP\_TO\_MONGO

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L1727)

<a name="wandb.apis.public.QueryGenerator.GROUP_OP_TO_MONGO"></a>
#### GROUP\_OP\_TO\_MONGO

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L1738)

<a name="wandb.apis.public.QueryGenerator.__init__"></a>
#### \_\_init\_\_

```python
 | __init__()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L1740)

<a name="wandb.apis.public.QueryGenerator.format_order_key"></a>
#### format\_order\_key

```python
 | @classmethod
 | format_order_key(cls, key)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L1744)

<a name="wandb.apis.public.QueryGenerator.key_to_server_path"></a>
#### key\_to\_server\_path

```python
 | key_to_server_path(key)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L1773)

<a name="wandb.apis.public.QueryGenerator.filter_to_mongo"></a>
#### filter\_to\_mongo

```python
 | filter_to_mongo(filter)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L1810)

<a name="wandb.apis.public.BetaReport"></a>
## BetaReport Objects

```python
class BetaReport(Attrs)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L1821)

BetaReport is a class associated with reports created in wandb.

WARNING: this API will likely change in a future release

**Attributes**:

- `name` _string_ - report name
- `description` _string_ - report descirpiton;
- `user` _User_ - the user that created the report
- `spec` _dict_ - the spec off the report;
- `updated_at` _string_ - timestamp of last update

<a name="wandb.apis.public.BetaReport.__init__"></a>
#### \_\_init\_\_

```python
 | __init__(client, attrs, entity=None, project=None)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L1834)

<a name="wandb.apis.public.BetaReport.sections"></a>
#### sections

```python
 | @property
 | sections()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L1843)

<a name="wandb.apis.public.BetaReport.runs"></a>
#### runs

```python
 | runs(section, per_page=50, only_selected=True)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L1846)

<a name="wandb.apis.public.BetaReport.updated_at"></a>
#### updated\_at

```python
 | @property
 | updated_at()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L1870)

<a name="wandb.apis.public.HistoryScan"></a>
## HistoryScan Objects

```python
class HistoryScan(object)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L1874)

<a name="wandb.apis.public.HistoryScan.QUERY"></a>
#### QUERY

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L1875)

<a name="wandb.apis.public.HistoryScan.__init__"></a>
#### \_\_init\_\_

```python
 | __init__(client, run, min_step, max_step, page_size=1000)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L1887)

<a name="wandb.apis.public.HistoryScan.__iter__"></a>
#### \_\_iter\_\_

```python
 | __iter__()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L1897)

<a name="wandb.apis.public.HistoryScan.__next__"></a>
#### \_\_next\_\_

```python
 | __next__()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L1903)

<a name="wandb.apis.public.HistoryScan.next"></a>
#### next

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L1913)

<a name="wandb.apis.public.SampledHistoryScan"></a>
## SampledHistoryScan Objects

```python
class SampledHistoryScan(object)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L1940)

<a name="wandb.apis.public.SampledHistoryScan.QUERY"></a>
#### QUERY

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L1941)

<a name="wandb.apis.public.SampledHistoryScan.__init__"></a>
#### \_\_init\_\_

```python
 | __init__(client, run, keys, min_step, max_step, page_size=1000)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L1953)

<a name="wandb.apis.public.SampledHistoryScan.__iter__"></a>
#### \_\_iter\_\_

```python
 | __iter__()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L1964)

<a name="wandb.apis.public.SampledHistoryScan.__next__"></a>
#### \_\_next\_\_

```python
 | __next__()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L1970)

<a name="wandb.apis.public.SampledHistoryScan.next"></a>
#### next

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L1980)

<a name="wandb.apis.public.ProjectArtifactTypes"></a>
## ProjectArtifactTypes Objects

```python
class ProjectArtifactTypes(Paginator)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L2012)

<a name="wandb.apis.public.ProjectArtifactTypes.QUERY"></a>
#### QUERY

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L2013)

<a name="wandb.apis.public.ProjectArtifactTypes.__init__"></a>
#### \_\_init\_\_

```python
 | __init__(client, entity, project, name=None, per_page=50)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L2031)

<a name="wandb.apis.public.ProjectArtifactTypes.length"></a>
#### length

```python
 | @property
 | length()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L2043)

<a name="wandb.apis.public.ProjectArtifactTypes.more"></a>
#### more

```python
 | @property
 | more()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L2048)

<a name="wandb.apis.public.ProjectArtifactTypes.cursor"></a>
#### cursor

```python
 | @property
 | cursor()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L2057)

<a name="wandb.apis.public.ProjectArtifactTypes.update_variables"></a>
#### update\_variables

```python
 | update_variables()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L2063)

<a name="wandb.apis.public.ProjectArtifactTypes.convert_objects"></a>
#### convert\_objects

```python
 | convert_objects()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L2066)

<a name="wandb.apis.public.ProjectArtifactCollections"></a>
## ProjectArtifactCollections Objects

```python
class ProjectArtifactCollections(Paginator)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L2077)

<a name="wandb.apis.public.ProjectArtifactCollections.QUERY"></a>
#### QUERY

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L2078)

<a name="wandb.apis.public.ProjectArtifactCollections.__init__"></a>
#### \_\_init\_\_

```python
 | __init__(client, entity, project, type_name, per_page=50)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L2109)

<a name="wandb.apis.public.ProjectArtifactCollections.length"></a>
#### length

```python
 | @property
 | length()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L2125)

<a name="wandb.apis.public.ProjectArtifactCollections.more"></a>
#### more

```python
 | @property
 | more()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L2134)

<a name="wandb.apis.public.ProjectArtifactCollections.cursor"></a>
#### cursor

```python
 | @property
 | cursor()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L2143)

<a name="wandb.apis.public.ProjectArtifactCollections.update_variables"></a>
#### update\_variables

```python
 | update_variables()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L2151)

<a name="wandb.apis.public.ProjectArtifactCollections.convert_objects"></a>
#### convert\_objects

```python
 | convert_objects()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L2154)

<a name="wandb.apis.public.RunArtifacts"></a>
## RunArtifacts Objects

```python
class RunArtifacts(Paginator)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L2170)

<a name="wandb.apis.public.RunArtifacts.OUTPUT_QUERY"></a>
#### OUTPUT\_QUERY

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L2171)

<a name="wandb.apis.public.RunArtifacts.INPUT_QUERY"></a>
#### INPUT\_QUERY

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L2199)

<a name="wandb.apis.public.RunArtifacts.__init__"></a>
#### \_\_init\_\_

```python
 | __init__(client, run, mode="logged", per_page=50)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L2227)

<a name="wandb.apis.public.RunArtifacts.length"></a>
#### length

```python
 | @property
 | length()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L2247)

<a name="wandb.apis.public.RunArtifacts.more"></a>
#### more

```python
 | @property
 | more()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L2254)

<a name="wandb.apis.public.RunArtifacts.cursor"></a>
#### cursor

```python
 | @property
 | cursor()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L2263)

<a name="wandb.apis.public.RunArtifacts.update_variables"></a>
#### update\_variables

```python
 | update_variables()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L2269)

<a name="wandb.apis.public.RunArtifacts.convert_objects"></a>
#### convert\_objects

```python
 | convert_objects()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L2272)

<a name="wandb.apis.public.ArtifactType"></a>
## ArtifactType Objects

```python
class ArtifactType(object)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L2285)

<a name="wandb.apis.public.ArtifactType.__init__"></a>
#### \_\_init\_\_

```python
 | __init__(client, entity, project, type_name, attrs=None)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L2286)

<a name="wandb.apis.public.ArtifactType.load"></a>
#### load

```python
 | load()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L2295)

<a name="wandb.apis.public.ArtifactType.id"></a>
#### id

```python
 | @property
 | id()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L2332)

<a name="wandb.apis.public.ArtifactType.name"></a>
#### name

```python
 | @property
 | name()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L2336)

<a name="wandb.apis.public.ArtifactType.collections"></a>
#### collections

```python
 | @normalize_exceptions
 | collections(per_page=50)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L2340)

Artifact collections

<a name="wandb.apis.public.ArtifactType.collection"></a>
#### collection

```python
 | collection(name)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L2346)

<a name="wandb.apis.public.ArtifactType.__repr__"></a>
#### \_\_repr\_\_

```python
 | __repr__()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L2351)

<a name="wandb.apis.public.ArtifactCollection"></a>
## ArtifactCollection Objects

```python
class ArtifactCollection(object)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L2355)

<a name="wandb.apis.public.ArtifactCollection.__init__"></a>
#### \_\_init\_\_

```python
 | __init__(client, entity, project, name, type, attrs=None)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L2356)

<a name="wandb.apis.public.ArtifactCollection.id"></a>
#### id

```python
 | @property
 | id()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L2365)

<a name="wandb.apis.public.ArtifactCollection.versions"></a>
#### versions

```python
 | @normalize_exceptions
 | versions(per_page=50)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L2369)

Artifact versions

<a name="wandb.apis.public.ArtifactCollection.__repr__"></a>
#### \_\_repr\_\_

```python
 | __repr__()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L2380)

<a name="wandb.apis.public.Artifact"></a>
## Artifact Objects

```python
class Artifact(object)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L2419)

<a name="wandb.apis.public.Artifact.QUERY"></a>
#### QUERY

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L2420)

<a name="wandb.apis.public.Artifact.from_id"></a>
#### from\_id

```python
 | @classmethod
 | from_id(cls, client, id)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L2442)

<a name="wandb.apis.public.Artifact.__init__"></a>
#### \_\_init\_\_

```python
 | __init__(client, entity, project, name, attrs=None)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L2478)

<a name="wandb.apis.public.Artifact.id"></a>
#### id

```python
 | @property
 | id()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L2500)

<a name="wandb.apis.public.Artifact.metadata"></a>
#### metadata

```python
 | @property
 | metadata()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L2504)

<a name="wandb.apis.public.Artifact.metadata"></a>
#### metadata

```python
 | @metadata.setter
 | metadata(metadata)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L2508)

<a name="wandb.apis.public.Artifact.manifest"></a>
#### manifest

```python
 | @property
 | manifest()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L2512)

<a name="wandb.apis.public.Artifact.digest"></a>
#### digest

```python
 | @property
 | digest()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L2516)

<a name="wandb.apis.public.Artifact.state"></a>
#### state

```python
 | @property
 | state()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L2520)

<a name="wandb.apis.public.Artifact.size"></a>
#### size

```python
 | @property
 | size()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L2524)

<a name="wandb.apis.public.Artifact.created_at"></a>
#### created\_at

```python
 | @property
 | created_at()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L2528)

<a name="wandb.apis.public.Artifact.updated_at"></a>
#### updated\_at

```python
 | @property
 | updated_at()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L2532)

<a name="wandb.apis.public.Artifact.description"></a>
#### description

```python
 | @property
 | description()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L2536)

<a name="wandb.apis.public.Artifact.description"></a>
#### description

```python
 | @description.setter
 | description(desc)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L2540)

<a name="wandb.apis.public.Artifact.type"></a>
#### type

```python
 | @property
 | type()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L2544)

<a name="wandb.apis.public.Artifact.name"></a>
#### name

```python
 | @property
 | name()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L2548)

<a name="wandb.apis.public.Artifact.aliases"></a>
#### aliases

```python
 | @property
 | aliases()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L2554)

<a name="wandb.apis.public.Artifact.aliases"></a>
#### aliases

```python
 | @aliases.setter
 | aliases(aliases)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L2558)

<a name="wandb.apis.public.Artifact.delete"></a>
#### delete

```python
 | delete()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L2566)

Delete artifact and it's files.

<a name="wandb.apis.public.Artifact.new_file"></a>
#### new\_file

```python
 | new_file(name, mode=None)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L2582)

<a name="wandb.apis.public.Artifact.add_file"></a>
#### add\_file

```python
 | add_file(path, name=None)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L2585)

<a name="wandb.apis.public.Artifact.add_dir"></a>
#### add\_dir

```python
 | add_dir(path, name=None)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L2588)

<a name="wandb.apis.public.Artifact.add_reference"></a>
#### add\_reference

```python
 | add_reference(path, name=None)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L2591)

<a name="wandb.apis.public.Artifact.get_path"></a>
#### get\_path

```python
 | get_path(name)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L2594)

<a name="wandb.apis.public.Artifact.get"></a>
#### get

```python
 | get(name)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L2666)

Returns the wandb.Media resource stored in the artifact. Media can be
stored in the artifact via Artifact#add(obj: wandbMedia, name: str)`

**Arguments**:

- `name` _str_ - name of resource.


**Returns**:

A `wandb.Media` which has been stored at `name`

<a name="wandb.apis.public.Artifact.download"></a>
#### download

```python
 | download(root=None)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L2705)

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

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L2745)

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

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L2780)

Persists artifact changes to the wandb backend.

<a name="wandb.apis.public.Artifact.verify"></a>
#### verify

```python
 | verify(root=None)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L2819)

Verify an artifact by checksumming its downloaded contents.

Raises a ValueError if the verification fails. Does not verify downloaded
reference files.

**Arguments**:

- `root` _str, optional_ - directory to download artifact to. If None
artifact will be downloaded to './artifacts/<self.name>/'

<a name="wandb.apis.public.Artifact.__repr__"></a>
#### \_\_repr\_\_

```python
 | __repr__()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L2851)

<a name="wandb.apis.public.ArtifactVersions"></a>
## ArtifactVersions Objects

```python
class ArtifactVersions(Paginator)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L2948)

An iterable collection of artifact versions associated with a project and optional filter.
This is generally used indirectly via the `Api`.artifact_versions method

<a name="wandb.apis.public.ArtifactVersions.QUERY"></a>
#### QUERY

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L2953)

<a name="wandb.apis.public.ArtifactVersions.__init__"></a>
#### \_\_init\_\_

```python
 | __init__(client, entity, project, collection_name, type, filters={}, order=None, per_page=50)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L2983)

<a name="wandb.apis.public.ArtifactVersions.length"></a>
#### length

```python
 | @property
 | length()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L3011)

<a name="wandb.apis.public.ArtifactVersions.more"></a>
#### more

```python
 | @property
 | more()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L3020)

<a name="wandb.apis.public.ArtifactVersions.cursor"></a>
#### cursor

```python
 | @property
 | cursor()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L3029)

<a name="wandb.apis.public.ArtifactVersions.convert_objects"></a>
#### convert\_objects

```python
 | convert_objects()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L3037)

<a name="wandb.apis.public.ArtifactFiles"></a>
## ArtifactFiles Objects

```python
class ArtifactFiles(Paginator)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L3054)

<a name="wandb.apis.public.ArtifactFiles.QUERY"></a>
#### QUERY

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L3055)

<a name="wandb.apis.public.ArtifactFiles.__init__"></a>
#### \_\_init\_\_

```python
 | __init__(client, artifact, names=None, per_page=50)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L3079)

<a name="wandb.apis.public.ArtifactFiles.length"></a>
#### length

```python
 | @property
 | length()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L3091)

<a name="wandb.apis.public.ArtifactFiles.more"></a>
#### more

```python
 | @property
 | more()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L3096)

<a name="wandb.apis.public.ArtifactFiles.cursor"></a>
#### cursor

```python
 | @property
 | cursor()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L3105)

<a name="wandb.apis.public.ArtifactFiles.update_variables"></a>
#### update\_variables

```python
 | update_variables()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L3113)

<a name="wandb.apis.public.ArtifactFiles.convert_objects"></a>
#### convert\_objects

```python
 | convert_objects()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L3116)

<a name="wandb.apis.public.ArtifactFiles.__repr__"></a>
#### \_\_repr\_\_

```python
 | __repr__()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/apis/public.py#L3124)

