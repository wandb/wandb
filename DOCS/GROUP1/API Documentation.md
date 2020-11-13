# Api
[![Badge](https://img.shields.io/badge/View%20source%20on%20GitHub-black?style=for-the-badge&logo=github)](https://github.com/wandb/client/blob/master/wandb/apis/public.py#L181-L518)

`Api`

Used for querying the wandb server.


| **Arguments** | **Datatype** | **Description** |
|:--:|:--:|:--|
|overrides|(dict)|You can set `base_url` if you are using a wandb server other than https://api.wandb.ai. You can also set defaults for `entity`, `project`, and `run`.|








**Example**

Most common way to initialize
```
    wandb.Api()
```


## Api.flush
[![Badge](https://img.shields.io/badge/View%20source%20on%20GitHub-black?style=for-the-badge&logo=github)](https://github.com/wandb/client/blob/master/wandb/apis/public.py#L276-L281)

`def flush(self):`

The api object keeps a local cache of runs, so if the state of the run may
change while executing your script you must clear the local cache with `api.flush()`
to get the latest values associated with the run.











## Api._parse_project_path
[![Badge](https://img.shields.io/badge/View%20source%20on%20GitHub-black?style=for-the-badge&logo=github)](https://github.com/wandb/client/blob/master/wandb/apis/public.py#L283-L292)

`def _parse_project_path(self, path):`

Returns project and entity for project specified by path











## Api._parse_path
[![Badge](https://img.shields.io/badge/View%20source%20on%20GitHub-black?style=for-the-badge&logo=github)](https://github.com/wandb/client/blob/master/wandb/apis/public.py#L294-L321)

`def _parse_path(self, path):`

Parses paths in the following formats:

url: entity/project/runs/run_id
path: entity/project/run_id
docker: entity/project:run_id

entity is optional and will fallback to the current logged in user.












## Api._parse_artifact_path
[![Badge](https://img.shields.io/badge/View%20source%20on%20GitHub-black?style=for-the-badge&logo=github)](https://github.com/wandb/client/blob/master/wandb/apis/public.py#L323-L336)

`def _parse_artifact_path(self, path):`

Returns project, entity and artifact name for project specified by path











## Api.projects
[![Badge](https://img.shields.io/badge/View%20source%20on%20GitHub-black?style=for-the-badge&logo=github)](https://github.com/wandb/client/blob/master/wandb/apis/public.py#L338-L358)

`def projects(self, entity=None, per_page=200):`

Get projects for a given entity.

| **Arguments** | **Datatype** | **Description** |
|:--:|:--:|:--|
|entity|(str)|Name of the entity requested. If None will fallback to default entity passed to `Api`. If no default entity, will raise a `ValueError`.|
|per_page|(int)|Sets the page size for query pagination. None will use the default size. Usually there is no reason to change this.|






**Reutrns**

A `Projects` object which is an iterable collection of `Project` objects.





## Api.reports
[![Badge](https://img.shields.io/badge/View%20source%20on%20GitHub-black?style=for-the-badge&logo=github)](https://github.com/wandb/client/blob/master/wandb/apis/public.py#L360-L391)

`def reports(self, path="", name=None, per_page=50):`

Get reports for a given project path.

WARNING: This api is in beta and will likely change in a future release


| **Arguments** | **Datatype** | **Description** |
|:--:|:--:|:--|
|path|(str)|path to project the report resides in, should be in the form: "entity/project"|
|name|(str)|optional name of the report requested.|
|per_page|(int)|Sets the page size for query pagination. None will use the default size. Usually there is no reason to change this.|






**Reutrns**

A `Reports` object which is an iterable collection of `BetaReport` objects.




## Api.runs
[![Badge](https://img.shields.io/badge/View%20source%20on%20GitHub-black?style=for-the-badge&logo=github)](https://github.com/wandb/client/blob/master/wandb/apis/public.py#L393-L442)

`def runs(self, path="", filters={}, order="-created_at", per_page=50):`

Return a set of runs from a project that match the filters provided.
You can filter by `config.*`, `summary.*`, `state`, `entity`, `createdAt`, etc.


| **Arguments** | **Datatype** | **Description** |
|:--:|:--:|:--|
|path|(str)|path to project, should be in the form: "entity/project"|
|filters|(dict)|queries for specific runs using the MongoDB query language. You can filter by run properties such as config.key, summary_metrics.key, state, entity, createdAt, etc. For example: {"config.experiment_name": "foo"} would find runs with a config entry of experiment name set to "foo" You can compose operations to make more complicated queries, see Reference for the language is at https://docs.mongodb.com/manual/reference/operator/query|
|order|(str)|Order can be `created_at`, `heartbeat_at`, `config.*.value`, or `summary_metrics.*`. If you prepend order with a + order is ascending. If you prepend order with a - order is descending (default). The default order is run.created_at from newest to oldest.|






**Reutrns**

A `Runs` object, which is an iterable collection of `Run` objects.


**Example**

Find runs in my_project config.experiment_name has been set to "foo"
```
```

Find runs in my_project config.experiment_name has been set to "foo" or "bar"
```
api.runs(path="my_entity/my_project",
```

Find runs in my_project sorted by ascending loss
```
```



## Api.run
[![Badge](https://img.shields.io/badge/View%20source%20on%20GitHub-black?style=for-the-badge&logo=github)](https://github.com/wandb/client/blob/master/wandb/apis/public.py#L444-L459)

`def run(self, path=""):`

Returns a single run by parsing path in the form entity/project/run_id.


| **Arguments** | **Datatype** | **Description** |
|:--:|:--:|:--|
|path|(str)|path to run in the form entity/project/run_id. If api.entity is set, this can be in the form project/run_id and if api.project is set this can just be the run_id.|






**Reutrns**

A `Run` object.




## Api.sweep
[![Badge](https://img.shields.io/badge/View%20source%20on%20GitHub-black?style=for-the-badge&logo=github)](https://github.com/wandb/client/blob/master/wandb/apis/public.py#L461-L477)

`def sweep(self, path=""):`

Returns a sweep by parsing path in the form entity/project/sweep_id.


| **Arguments** | **Datatype** | **Description** |
|:--:|:--:|:--|
|path|(str, optional)|path to sweep in the form entity/project/sweep_id. If api.entity is set, this can be in the form project/sweep_id and if api.project is set this can just be the sweep_id.|






**Reutrns**

A `Sweep` object.




## Api.artifact
[![Badge](https://img.shields.io/badge/View%20source%20on%20GitHub-black?style=for-the-badge&logo=github)](https://github.com/wandb/client/blob/master/wandb/apis/public.py#L495-L515)

`def artifact(self, name, type=None):`

Returns a single artifact by parsing path in the form entity/project/run_id.


| **Arguments** | **Datatype** | **Description** |
|:--:|:--:|:--|
|name|(str)|An artifact name. May be prefixed with entity/project. Valid names can be in the following forms: name:version name:alias digest|
|type|(str, optional)|The type of artifact to fetch.|






**Reutrns**

A `Artifact` object.




# Projects
[![Badge](https://img.shields.io/badge/View%20source%20on%20GitHub-black?style=for-the-badge&logo=github)](https://github.com/wandb/client/blob/master/wandb/apis/public.py#L619-L678)

`Projects`

An iterable collection of `Project` objects.












# Project
[![Badge](https://img.shields.io/badge/View%20source%20on%20GitHub-black?style=for-the-badge&logo=github)](https://github.com/wandb/client/blob/master/wandb/apis/public.py#L681-L699)

`Project`

A project is a namespace for runs











# Runs
[![Badge](https://img.shields.io/badge/View%20source%20on%20GitHub-black?style=for-the-badge&logo=github)](https://github.com/wandb/client/blob/master/wandb/apis/public.py#L702-L804)

`Runs`

An iterable collection of runs associated with a project and optional filter.
This is generally used indirectly via the `Api`.runs method












# Run
[![Badge](https://img.shields.io/badge/View%20source%20on%20GitHub-black?style=for-the-badge&logo=github)](https://github.com/wandb/client/blob/master/wandb/apis/public.py#L807-L1314)

`Run`

A single run associated with an entity and project.




| **Attributes** | **Datatype** | **Description** |
|:--:|:--:|:--|
|tags|([str])|a list of tags associated with the run|
|url|(str)|the url of this run|
|id|(str)|unique identifier for the run (defaults to eight characters)|
|name|(str)|the name of the run|
|state|(str)|one of: running, finished, crashed, aborted|
|config|(dict)|a dict of hyperparameters associated with the run|
|created_at|(str)|ISO timestamp when the run was started|
|system_metrics|(dict)|the latest system metrics recorded for the run|
|summary|(dict)|A mutable dict-like property that holds the current summary. Calling update will persist any changes.|
|project|(str)|the project associated with the run|
|entity|(str)|the name of the entity associated with the run|
|user|(str)|the name of the user who created the run|
|path|(str)|Unique identifier [entity]/[project]/[run_id]|
|notes|(str)|Notes about the run|
|read_only|(boolean)|Whether the run is editable|
|history_keys|(str)|Keys of the history metrics that have been logged with `wandb.log({key: value})`|








## Run.__init__
[![Badge](https://img.shields.io/badge/View%20source%20on%20GitHub-black?style=for-the-badge&logo=github)](https://github.com/wandb/client/blob/master/wandb/apis/public.py#L832-L852)

`def __init__(self, client, entity, project, run_id, attrs={}):`

Run is always initialized by calling api.runs() where api is an instance of wandb.Api












## Run.create
[![Badge](https://img.shields.io/badge/View%20source%20on%20GitHub-black?style=for-the-badge&logo=github)](https://github.com/wandb/client/blob/master/wandb/apis/public.py#L889-L927)

`def create(cls, api, run_id=None, project=None, entity=None):`

Create a run for the given project











## Run.update
[![Badge](https://img.shields.io/badge/View%20source%20on%20GitHub-black?style=for-the-badge&logo=github)](https://github.com/wandb/client/blob/master/wandb/apis/public.py#L995-L1022)

`def update(self):`

Persists changes to the run object to the wandb backend.












## Run._exec
[![Badge](https://img.shields.io/badge/View%20source%20on%20GitHub-black?style=for-the-badge&logo=github)](https://github.com/wandb/client/blob/master/wandb/apis/public.py#L1034-L1038)

`def _exec(self, query, **kwargs):`

Execute a query against the cloud backend











## Run.files
[![Badge](https://img.shields.io/badge/View%20source%20on%20GitHub-black?style=for-the-badge&logo=github)](https://github.com/wandb/client/blob/master/wandb/apis/public.py#L1072-L1082)

`def files(self, names=[], per_page=50):`



| **Arguments** | **Datatype** | **Description** |
|:--:|:--:|:--|
|names|(list)|names of the requested files, if empty returns all files|
|per_page|(int)|number of results per page|






**Reutrns**

A `Files` object, which is an iterator over `File` obejcts.




## Run.file
[![Badge](https://img.shields.io/badge/View%20source%20on%20GitHub-black?style=for-the-badge&logo=github)](https://github.com/wandb/client/blob/master/wandb/apis/public.py#L1084-L1093)

`def file(self, name):`



| **Arguments** | **Datatype** | **Description** |
|:--:|:--:|:--|
|name|(str)|name of requested file.|






**Reutrns**

A `File` matching the name argument.




## Run.upload_file
[![Badge](https://img.shields.io/badge/View%20source%20on%20GitHub-black?style=for-the-badge&logo=github)](https://github.com/wandb/client/blob/master/wandb/apis/public.py#L1095-L1116)

`def upload_file(self, path, root="."):`



| **Arguments** | **Datatype** | **Description** |
|:--:|:--:|:--|
|path|(str)|name of file to upload.|
|root|(str)|the root path to save the file relative to. i.e. If you want to have the file saved in the run as "my_dir/file.txt" and you're currently in "my_dir" you would set root to "../"|






**Reutrns**

A `File` matching the name argument.




## Run.history
[![Badge](https://img.shields.io/badge/View%20source%20on%20GitHub-black?style=for-the-badge&logo=github)](https://github.com/wandb/client/blob/master/wandb/apis/public.py#L1118-L1150)

`def history( self, samples=500, keys=None, x_axis="_step", pandas=True, stream="default" ):`

Returns sampled history metrics for a run.  This is simpler and faster if you are ok with
the history records being sampled.


| **Arguments** | **Datatype** | **Description** |
|:--:|:--:|:--|
|samples|(int, optional)|The number of samples to return|
|pandas|(bool, optional)|Return a pandas dataframe|
|keys|(list, optional)|Only return metrics for specific keys|
|x_axis|(str, optional)|Use this metric as the xAxis defaults to _step|
|stream|(str, optional)|"default" for metrics, "system" for machine metrics|






**Reutrns**

If pandas=True returns a `pandas.DataFrame` of history metrics.
If pandas=False returns a list of dicts of history metrics.




## Run.scan_history
[![Badge](https://img.shields.io/badge/View%20source%20on%20GitHub-black?style=for-the-badge&logo=github)](https://github.com/wandb/client/blob/master/wandb/apis/public.py#L1152-L1198)

`def scan_history(self, keys=None, page_size=1000, min_step=None, max_step=None):`

Returns an iterable collection of all history records for a run.


| **Arguments** | **Datatype** | **Description** |
|:--:|:--:|:--|
|keys|([str], optional)|only fetch these keys, and only fetch rows that have all of keys defined.|
|page_size|(int, optional)|size of pages to fetch from the api|






**Reutrns**

An iterable collection over history records (dict).




## Run.use_artifact
[![Badge](https://img.shields.io/badge/View%20source%20on%20GitHub-black?style=for-the-badge&logo=github)](https://github.com/wandb/client/blob/master/wandb/apis/public.py#L1209-L1234)

`def use_artifact(self, artifact):`

 Declare an artifact as an input to a run.


| **Arguments** | **Datatype** | **Description** |
|:--:|:--:|:--|
|artifact|(`Artifact`)|An artifact returned from `wandb.Api().artifact(name)`|






**Reutrns**

A `Artifact` object.




## Run.log_artifact
[![Badge](https://img.shields.io/badge/View%20source%20on%20GitHub-black?style=for-the-badge&logo=github)](https://github.com/wandb/client/blob/master/wandb/apis/public.py#L1236-L1268)

`def log_artifact(self, artifact, aliases=None):`

 Declare an artifact as output of a run.


| **Arguments** | **Datatype** | **Description** |
|:--:|:--:|:--|
|artifact|(`Artifact`)|An artifact returned from `wandb.Api().artifact(name)`|
|aliases|(list, optional)|Aliases to apply to this artifact|






**Reutrns**

A `Artifact` object.




# Sweep
[![Badge](https://img.shields.io/badge/View%20source%20on%20GitHub-black?style=for-the-badge&logo=github)](https://github.com/wandb/client/blob/master/wandb/apis/public.py#L1317-L1495)

`Sweep`

A set of runs associated with a sweep
Instantiate with:
  api.sweep(sweep_path)




| **Attributes** | **Datatype** | **Description** |
|:--:|:--:|:--|
|runs|(`Runs`)|list of runs|
|id|(str)|sweep id|
|project|(str)|name of project|
|config|(str)|dictionary of sweep configuration|








## Sweep.best_run
[![Badge](https://img.shields.io/badge/View%20source%20on%20GitHub-black?style=for-the-badge&logo=github)](https://github.com/wandb/client/blob/master/wandb/apis/public.py#L1403-L1426)

`def best_run(self, order=None): "Returns the best run sorted by the metric defined in config or the order passed in" if order is None: order = self.order else: order = QueryGenerator.format_order_key(order) if order is None: wandb.termwarn( "No order specified and couldn't find metric in sweep config, returning most recent run" ) else: wandb.termlog("Sorting runs by %s" % order) filters = {"$and": [{"sweep": self.id}]} try: return Runs( self.client, self.entity, self.project, order=order, filters=filters, per_page=1, )[0] except IndexError: return None @property def path(self): return [ urllib.parse.quote_plus(str(self.entity)), urllib.parse.quote_plus(str(self.project)), urllib.parse.quote_plus(str(self.id)), ] @property def url(self): path = self.path path.insert(2, "sweeps") return self.client.app_url + "/".join(path) @classmethod def get( cls, client, entity=None, project=None, sid=None, withRuns=True, # noqa: N803 order=None, query=None, **kwargs ):`

Execute a query against the cloud backend











## Sweep.get
[![Badge](https://img.shields.io/badge/View%20source%20on%20GitHub-black?style=for-the-badge&logo=github)](https://github.com/wandb/client/blob/master/wandb/apis/public.py#L1442-L1492)

`def get( cls, client, entity=None, project=None, sid=None, withRuns=True, # noqa: N803 order=None, query=None, **kwargs ):`

Execute a query against the cloud backend











# Files
[![Badge](https://img.shields.io/badge/View%20source%20on%20GitHub-black?style=for-the-badge&logo=github)](https://github.com/wandb/client/blob/master/wandb/apis/public.py#L1498-L1561)

`Files`

Files is an iterable collection of `File` objects.











# File
[![Badge](https://img.shields.io/badge/View%20source%20on%20GitHub-black?style=for-the-badge&logo=github)](https://github.com/wandb/client/blob/master/wandb/apis/public.py#L1564-L1640)

`File`

File is a class associated with a file saved by wandb.




| **Attributes** | **Datatype** | **Description** |
|:--:|:--:|:--|
|name|(string)|filename|
|url|(string)|path to file|
|md5|(string)|md5 of file|
|mimetype|(string)|mimetype of file|
|updated_at|(string)|timestamp of last update|
|size|(int)|size of file in bytes|








## File.download
[![Badge](https://img.shields.io/badge/View%20source%20on%20GitHub-black?style=for-the-badge&logo=github)](https://github.com/wandb/client/blob/master/wandb/apis/public.py#L1615-L1636)

`def download(self, root=".", replace=False):`

Downloads a file previously saved by a run from the wandb server.


| **Arguments** | **Datatype** | **Description** |
|:--:|:--:|:--|
|replace|(boolean)|If `True`, download will overwrite a local file if it exists. Defaults to `False`.|
|root|(str)|Local directory to save the file. Defaults to ".".|










# Reports
[![Badge](https://img.shields.io/badge/View%20source%20on%20GitHub-black?style=for-the-badge&logo=github)](https://github.com/wandb/client/blob/master/wandb/apis/public.py#L1644-L1721)

`Reports`

Reports is an iterable collection of `BetaReport` objects.











# QueryGenerator
[![Badge](https://img.shields.io/badge/View%20source%20on%20GitHub-black?style=for-the-badge&logo=github)](https://github.com/wandb/client/blob/master/wandb/apis/public.py#L1724-L1816)

`QueryGenerator`

QueryGenerator is a helper object to write filters for runs











# BetaReport
[![Badge](https://img.shields.io/badge/View%20source%20on%20GitHub-black?style=for-the-badge&logo=github)](https://github.com/wandb/client/blob/master/wandb/apis/public.py#L1821-L1871)

`BetaReport`

BetaReport is a class associated with reports created in wandb.

WARNING: this API will likely change in a future release




| **Attributes** | **Datatype** | **Description** |
|:--:|:--:|:--|
|name|(string)|report name|
|description|(string)|report descirpiton;|
|user|(User)|the user that created the report|
|spec|(dict)|the spec off the report;|
|updated_at|(string)|timestamp of last update|








# ArtifactType
[![Badge](https://img.shields.io/badge/View%20source%20on%20GitHub-black?style=for-the-badge&logo=github)](https://github.com/wandb/client/blob/master/wandb/apis/public.py#L2285-L2352)















## ArtifactType.collections
[![Badge](https://img.shields.io/badge/View%20source%20on%20GitHub-black?style=for-the-badge&logo=github)](https://github.com/wandb/client/blob/master/wandb/apis/public.py#L2339-L2343)

`def collections(self, per_page=50):`

Artifact collections











# ArtifactCollection
[![Badge](https://img.shields.io/badge/View%20source%20on%20GitHub-black?style=for-the-badge&logo=github)](https://github.com/wandb/client/blob/master/wandb/apis/public.py#L2355-L2381)















## ArtifactCollection.versions
[![Badge](https://img.shields.io/badge/View%20source%20on%20GitHub-black?style=for-the-badge&logo=github)](https://github.com/wandb/client/blob/master/wandb/apis/public.py#L2368-L2377)

`def versions(self, per_page=50):`

Artifact versions











# _determine_artifact_root
[![Badge](https://img.shields.io/badge/View%20source%20on%20GitHub-black?style=for-the-badge&logo=github)](https://github.com/wandb/client/blob/master/wandb/apis/public.py#L2398-L2416)

`def _determine_artifact_root(source_path, target_path):`

Helper function to determine the artifact root of `target_path` by comparing to
an existing artifact asset in `source`path`. This is used in reference artifact resolution"""
abs_source_path = os.path.abspath(source_path)
abs_target_path = os.path.abspath(target_path)

# Break the source path into parts
source_path_parts = _path_to_parts(abs_source_path)
target_path_parts = _path_to_parts(abs_target_path)

# Buildup a shared path (ending with the first difference in the target)
shared_path = []
while len(source_path_parts) > 0 and len(target_path_parts) > 0:
comp = target_path_parts.pop(0)
shared_path.append(comp)
if comp != source_path_parts.pop(0):
    break












# Artifact
[![Badge](https://img.shields.io/badge/View%20source%20on%20GitHub-black?style=for-the-badge&logo=github)](https://github.com/wandb/client/blob/master/wandb/apis/public.py#L2419-L2945)















## Artifact.delete
[![Badge](https://img.shields.io/badge/View%20source%20on%20GitHub-black?style=for-the-badge&logo=github)](https://github.com/wandb/client/blob/master/wandb/apis/public.py#L2566-L2580)

`def delete(self):`

Delete artifact and it's files.











## Artifact.get
[![Badge](https://img.shields.io/badge/View%20source%20on%20GitHub-black?style=for-the-badge&logo=github)](https://github.com/wandb/client/blob/master/wandb/apis/public.py#L2666-L2703)

`def get(self, name):`

Returns the wandb.Media resource stored in the artifact. Media can be
stored in the artifact via Artifact#add(obj: wandbMedia, name: str)`

| **Arguments** | **Datatype** | **Description** |
|:--:|:--:|:--|
|name|(str)|name of resource.|






**Reutrns**

A `wandb.Media` which has been stored at `name`




## Artifact.download
[![Badge](https://img.shields.io/badge/View%20source%20on%20GitHub-black?style=for-the-badge&logo=github)](https://github.com/wandb/client/blob/master/wandb/apis/public.py#L2705-L2743)

`def download(root=None): root = root or default_root if entry.ref is not None: cache_path = storage_policy.load_reference( parent_self, name, manifest.entries[name], local=True ) else: cache_path = storage_policy.load_file( parent_self, name, manifest.entries[name] ) return ArtifactEntry().copy(cache_path, os.path.join(root, name)) @staticmethod def ref(): if entry.ref is not None: return storage_policy.load_reference( parent_self, name, manifest.entries[name], local=False ) raise ValueError("Only reference entries support ref().") @staticmethod def ref_url(): return ( "wandb-artifact://" + util.b64_to_hex_id(parent_self.id) + "/" + name ) return ArtifactEntry() def get(self, name):`

Returns the wandb.Media resource stored in the artifact. Media can be
stored in the artifact via Artifact#add(obj: wandbMedia, name: str)`

| **Arguments** | **Datatype** | **Description** |
|:--:|:--:|:--|
|name|(str)|name of resource.|






**Reutrns**

A `wandb.Media` which has been stored at `name`




## Artifact.file
[![Badge](https://img.shields.io/badge/View%20source%20on%20GitHub-black?style=for-the-badge&logo=github)](https://github.com/wandb/client/blob/master/wandb/apis/public.py#L2745-L2766)

`def file(self, root=None):`

Download a single file artifact to dir specified by the <root>


| **Arguments** | **Datatype** | **Description** |
|:--:|:--:|:--|
|root|(str, optional)|directory to download artifact to. If None artifact will be downloaded to './artifacts/<self.name>/'|






**Reutrns**

The full path of the downloaded file




## Artifact.save
[![Badge](https://img.shields.io/badge/View%20source%20on%20GitHub-black?style=for-the-badge&logo=github)](https://github.com/wandb/client/blob/master/wandb/apis/public.py#L2779-L2817)

`def save(self):`

Persists artifact changes to the wandb backend.












## Artifact.verify
[![Badge](https://img.shields.io/badge/View%20source%20on%20GitHub-black?style=for-the-badge&logo=github)](https://github.com/wandb/client/blob/master/wandb/apis/public.py#L2819-L2844)

`def verify(self, root=None):`

Verify an artifact by checksumming its downloaded contents.

Raises a ValueError if the verification fails. Does not verify downloaded
reference files.


| **Arguments** | **Datatype** | **Description** |
|:--:|:--:|:--|
|root|(str, optional)|directory to download artifact to. If None artifact will be downloaded to './artifacts/<self.name>/'|










# ArtifactVersions
[![Badge](https://img.shields.io/badge/View%20source%20on%20GitHub-black?style=for-the-badge&logo=github)](https://github.com/wandb/client/blob/master/wandb/apis/public.py#L2948-L3050)

`ArtifactVersions`

An iterable collection of artifact versions associated with a project and optional filter.
This is generally used indirectly via the `Api`.artifact_versions method












