---
title: Data Types
---

<a name="wandb.data_types"></a>
# wandb.data\_types

[[source]](https://github.com/wandb/client/blob/21787ccda9c60578fcf0c7f7b0d06c887b48a343/wandb/data_types.py#L1)

Wandb has special data types for logging rich visualizations.

All of the special data types are subclasses of WBValue. All of the data types
serialize to JSON, since that is what wandb uses to save the objects locally
and upload them to the W&B server.

<a name="wandb.data_types.WBValue"></a>
## WBValue Objects

```python
class WBValue(object)
```

[[source]](https://github.com/wandb/client/blob/21787ccda9c60578fcf0c7f7b0d06c887b48a343/wandb/data_types.py#L83)

Abstract parent class for things that can be logged by wandb.log() and
visualized by wandb.

The objects will be serialized as JSON and always have a _type attribute
that indicates how to interpret the other fields.

<a name="wandb.data_types.WBValue.to_json"></a>
#### to\_json

```python
 | to_json(run_or_artifact)
```

[[source]](https://github.com/wandb/client/blob/21787ccda9c60578fcf0c7f7b0d06c887b48a343/wandb/data_types.py#L100)

Serializes the object into a JSON blob, using a run or artifact to store additional data.

**Arguments**:

- `run_or_artifact` _wandb.Run | wandb.Artifact_ - the Run or Artifact for which this object should be generating
JSON for - this is useful to to store additional data if needed.


**Returns**:

- `dict` - JSON representation

<a name="wandb.data_types.WBValue.from_json"></a>
#### from\_json

```python
 | @classmethod
 | from_json(cls, json_obj, source_artifact)
```

[[source]](https://github.com/wandb/client/blob/21787ccda9c60578fcf0c7f7b0d06c887b48a343/wandb/data_types.py#L113)

Deserialize a `json_obj` into it's class representation. If additional resources were stored in the
`run_or_artifact` artifact during the `to_json` call, then those resources are expected to be in
the `source_artifact`.

**Arguments**:

- `json_obj` _dict_ - A JSON dictionary to deserialize
- `source_artifact` _wandb.Artifact_ - An artifact which will hold any additional resources which were stored
during the `to_json` function.

<a name="wandb.data_types.WBValue.with_suffix"></a>
#### with\_suffix

```python
 | @classmethod
 | with_suffix(cls, name, filetype="json")
```

[[source]](https://github.com/wandb/client/blob/21787ccda9c60578fcf0c7f7b0d06c887b48a343/wandb/data_types.py#L126)

Helper function to return the name with suffix added if not already

**Arguments**:

- `name` _str_ - the name of the file
- `filetype` _str, optional_ - the filetype to use. Defaults to "json".


**Returns**:

- `str` - a filename which is suffixed with it's `artifact_type` followed by the filetype

<a name="wandb.data_types.WBValue.init_from_json"></a>
#### init\_from\_json

```python
 | @staticmethod
 | init_from_json(json_obj, source_artifact)
```

[[source]](https://github.com/wandb/client/blob/21787ccda9c60578fcf0c7f7b0d06c887b48a343/wandb/data_types.py#L145)

Looks through all subclasses and tries to match the json obj with the class which created it. It will then
call that subclass' `from_json` method. Importantly, this function will set the return object's `source_artifact`
attribute to the passed in source artifact. This is critical for artifact bookkeeping. If you choose to create
a wandb.Value via it's `from_json` method, make sure to properly set this `artifact_source` to avoid data duplication.

**Arguments**:

- `json_obj` _dict_ - A JSON dictionary to deserialize. It must contain a `_type` key. The value of
this key is used to lookup the correct subclass to use.
- `source_artifact` _wandb.Artifact_ - An artifact which will hold any additional resources which were stored
during the `to_json` function.


**Returns**:

- `wandb.Value` - a newly created instance of a subclass of wandb.Value

<a name="wandb.data_types.WBValue.type_mapping"></a>
#### type\_mapping

```python
 | @staticmethod
 | type_mapping()
```

[[source]](https://github.com/wandb/client/blob/21787ccda9c60578fcf0c7f7b0d06c887b48a343/wandb/data_types.py#L169)

Returns a map from `artifact_type` to subclass. Used to lookup correct types for deserialization.

**Returns**:

- `dict` - dictionary of str:class

<a name="wandb.data_types.WBValue.artifact_source"></a>
#### artifact\_source

```python
 | @property
 | artifact_source()
```

[[source]](https://github.com/wandb/client/blob/21787ccda9c60578fcf0c7f7b0d06c887b48a343/wandb/data_types.py#L196)

Getter which returns the object's artifact source

**Returns**:

- `dict` - {"artifact": wandb.Artifact, "name": str} the artifact from which this object was originally
stored as well as the name (optional)

<a name="wandb.data_types.WBValue.artifact_source"></a>
#### artifact\_source

```python
 | @artifact_source.setter
 | artifact_source(artifact_source)
```

[[source]](https://github.com/wandb/client/blob/21787ccda9c60578fcf0c7f7b0d06c887b48a343/wandb/data_types.py#L206)

Setter for artifact source

**Arguments**:

- `dict` - {"artifact": wandb.Artifact, "name": str} the artifact from which this object was originally
stored as well as the name (optional)

<a name="wandb.data_types.Histogram"></a>
## Histogram Objects

```python
class Histogram(WBValue)
```

[[source]](https://github.com/wandb/client/blob/21787ccda9c60578fcf0c7f7b0d06c887b48a343/wandb/data_types.py#L216)

wandb class for histograms

This object works just like numpy's histogram function
https://docs.scipy.org/doc/numpy/reference/generated/numpy.histogram.html

**Examples**:

Generate histogram from a sequence
```
wandb.Histogram([1,2,3])
```

Efficiently initialize from np.histogram.
```
hist = np.histogram(data)
wandb.Histogram(np_histogram=hist)
```


**Arguments**:

- `sequence` _array_like_ - input data for histogram
- `np_histogram` _numpy histogram_ - alternative input of a precoomputed histogram
- `num_bins` _int_ - Number of bins for the histogram.  The default number of bins
is 64.  The maximum number of bins is 512


**Attributes**:

- `bins` _[float]_ - edges of bins
- `histogram` _[int]_ - number of elements falling in each bin

<a name="wandb.data_types.Media"></a>
## Media Objects

```python
class Media(WBValue)
```

[[source]](https://github.com/wandb/client/blob/21787ccda9c60578fcf0c7f7b0d06c887b48a343/wandb/data_types.py#L285)

A WBValue that we store as a file outside JSON and show in a media panel
on the front end.

If necessary, we move or copy the file into the Run's media directory so that it gets
uploaded.

<a name="wandb.data_types.Media.bind_to_run"></a>
#### bind\_to\_run

```python
 | bind_to_run(run, key, step, id_=None)
```

[[source]](https://github.com/wandb/client/blob/21787ccda9c60578fcf0c7f7b0d06c887b48a343/wandb/data_types.py#L332)

Bind this object to a particular Run.

Calling this function is necessary so that we have somewhere specific to
put the file associated with this object, from which other Runs can
refer to it.

<a name="wandb.data_types.Media.to_json"></a>
#### to\_json

```python
 | to_json(run)
```

[[source]](https://github.com/wandb/client/blob/21787ccda9c60578fcf0c7f7b0d06c887b48a343/wandb/data_types.py#L371)

Serializes the object into a JSON blob, using a run or artifact to store additional data. If `run_or_artifact`
is a wandb.Run then `self.bind_to_run()` must have been previously been called.

**Arguments**:

- `run_or_artifact` _wandb.Run | wandb.Artifact_ - the Run or Artifact for which this object should be generating
JSON for - this is useful to to store additional data if needed.


**Returns**:

- `dict` - JSON representation

<a name="wandb.data_types.BatchableMedia"></a>
## BatchableMedia Objects

```python
class BatchableMedia(Media)
```

[[source]](https://github.com/wandb/client/blob/21787ccda9c60578fcf0c7f7b0d06c887b48a343/wandb/data_types.py#L410)

Parent class for Media we treat specially in batches, like images and
thumbnails.

Apart from images, we just use these batches to help organize files by name
in the media directory.

<a name="wandb.data_types.Table"></a>
## Table Objects

```python
class Table(Media)
```

[[source]](https://github.com/wandb/client/blob/21787ccda9c60578fcf0c7f7b0d06c887b48a343/wandb/data_types.py#L426)

This is a table designed to display sets of records.

**Arguments**:

- `columns` _[str]_ - Names of the columns in the table.
Defaults to ["Input", "Output", "Expected"].
- `data` _array_ - 2D Array of values that will be displayed as strings.
- `dataframe` _pandas.DataFrame_ - DataFrame object used to create the table.
When set, the other arguments are ignored.

<a name="wandb.data_types.Table.__init__"></a>
#### \_\_init\_\_

```python
 | __init__(columns=["Input", "Output", "Expected"], data=None, rows=None, dataframe=None)
```

[[source]](https://github.com/wandb/client/blob/21787ccda9c60578fcf0c7f7b0d06c887b48a343/wandb/data_types.py#L441)

rows is kept for legacy reasons, we use data to mimic the Pandas api

<a name="wandb.data_types.Table.add_data"></a>
#### add\_data

```python
 | add_data(*data)
```

[[source]](https://github.com/wandb/client/blob/21787ccda9c60578fcf0c7f7b0d06c887b48a343/wandb/data_types.py#L482)

Add a row of data to the table. Argument length should match column length

<a name="wandb.data_types.Audio"></a>
## Audio Objects

```python
class Audio(BatchableMedia)
```

[[source]](https://github.com/wandb/client/blob/21787ccda9c60578fcf0c7f7b0d06c887b48a343/wandb/data_types.py#L575)

Wandb class for audio clips.

**Arguments**:

- `data_or_path` _string or numpy array_ - A path to an audio file
or a numpy array of audio data.
- `sample_rate` _int_ - Sample rate, required when passing in raw
numpy array of audio data.
- `caption` _string_ - Caption to display with audio.

<a name="wandb.data_types.Audio.__init__"></a>
#### \_\_init\_\_

```python
 | __init__(data_or_path, sample_rate=None, caption=None)
```

[[source]](https://github.com/wandb/client/blob/21787ccda9c60578fcf0c7f7b0d06c887b48a343/wandb/data_types.py#L587)

Accepts a path to an audio file or a numpy array of audio data.

<a name="wandb.data_types.Object3D"></a>
## Object3D Objects

```python
class Object3D(BatchableMedia)
```

[[source]](https://github.com/wandb/client/blob/21787ccda9c60578fcf0c7f7b0d06c887b48a343/wandb/data_types.py#L680)

Wandb class for 3D point clouds.

**Arguments**:

data_or_path (numpy array, string, io):
Object3D can be initialized from a file or a numpy array.

The file types supported are obj, gltf, babylon, stl.  You can pass a path to
a file or an io object and a file_type which must be one of `'obj', 'gltf', 'babylon', 'stl'`.

The shape of the numpy array must be one of either:
```
[[x y z],       ...] nx3
[x y z c],     ...] nx4 where c is a category with supported range [1, 14]
[x y z r g b], ...] nx4 where is rgb is color
```

<a name="wandb.data_types.Molecule"></a>
## Molecule Objects

```python
class Molecule(BatchableMedia)
```

[[source]](https://github.com/wandb/client/blob/21787ccda9c60578fcf0c7f7b0d06c887b48a343/wandb/data_types.py#L832)

Wandb class for Molecular data

**Arguments**:

data_or_path (string, io):
Molecule can be initialized from a file name or an io object.

<a name="wandb.data_types.Html"></a>
## Html Objects

```python
class Html(BatchableMedia)
```

[[source]](https://github.com/wandb/client/blob/21787ccda9c60578fcf0c7f7b0d06c887b48a343/wandb/data_types.py#L925)

Wandb class for arbitrary html

**Arguments**:

- `data` _string or io object_ - HTML to display in wandb
- `inject` _boolean_ - Add a stylesheet to the HTML object.  If set
to False the HTML will pass through unchanged.

<a name="wandb.data_types.Video"></a>
## Video Objects

```python
class Video(BatchableMedia)
```

[[source]](https://github.com/wandb/client/blob/21787ccda9c60578fcf0c7f7b0d06c887b48a343/wandb/data_types.py#L994)

Wandb representation of video.

**Arguments**:

data_or_path (numpy array, string, io):
Video can be initialized with a path to a file or an io object.
The format must be "gif", "mp4", "webm" or "ogg".
The format must be specified with the format argument.
Video can be initialized with a numpy tensor.
The numpy tensor must be either 4 dimensional or 5 dimensional.
Channels should be (time, channel, height, width) or
(batch, time, channel, height width)
- `caption` _string_ - caption associated with the video for display
- `fps` _int_ - frames per second for video. Default is 4.
- `format` _string_ - format of video, necessary if initializing with path or io object.

<a name="wandb.data_types.Classes"></a>
## Classes Objects

```python
class Classes(Media)
```

[[source]](https://github.com/wandb/client/blob/21787ccda9c60578fcf0c7f7b0d06c887b48a343/wandb/data_types.py#L1150)

<a name="wandb.data_types.Classes.__init__"></a>
#### \_\_init\_\_

```python
 | __init__(class_set)
```

[[source]](https://github.com/wandb/client/blob/21787ccda9c60578fcf0c7f7b0d06c887b48a343/wandb/data_types.py#L1153)

Classes is holds class metadata intended to be used in concert with other objects when visualizing artifacts

**Arguments**:

- `class_set` _list_ - list of dicts in the form of {"id":int|str, "name":str}

<a name="wandb.data_types.JoinedTable"></a>
## JoinedTable Objects

```python
class JoinedTable(Media)
```

[[source]](https://github.com/wandb/client/blob/21787ccda9c60578fcf0c7f7b0d06c887b48a343/wandb/data_types.py#L1180)

Joins two tables for visualization in the Artifact UI

**Arguments**:

table1 (str, wandb.Table):
the path of a wandb.Table or the table object
table2 (str, wandb.Table):
the path of a wandb.Table or the table object
join_key (str, [str, str]):
key or keys to perform the join

<a name="wandb.data_types.Image"></a>
## Image Objects

```python
class Image(BatchableMedia)
```

[[source]](https://github.com/wandb/client/blob/21787ccda9c60578fcf0c7f7b0d06c887b48a343/wandb/data_types.py#L1277)

Wandb class for images.

**Arguments**:

- `data_or_path` _numpy array, string, io_ - Accepts numpy array of
image data, or a PIL image. The class attempts to infer
the data format and converts it.
- `mode` _string_ - The PIL mode for an image. Most common are "L", "RGB",
"RGBA". Full explanation at https://pillow.readthedocs.io/en/4.2.x/handbook/concepts.html#concept-modes.
- `caption` _string_ - Label for display of image.

<a name="wandb.data_types.Image.guess_mode"></a>
#### guess\_mode

```python
 | guess_mode(data)
```

[[source]](https://github.com/wandb/client/blob/21787ccda9c60578fcf0c7f7b0d06c887b48a343/wandb/data_types.py#L1558)

Guess what type of image the np.array is representing

<a name="wandb.data_types.Image.to_uint8"></a>
#### to\_uint8

```python
 | @classmethod
 | to_uint8(data)
```

[[source]](https://github.com/wandb/client/blob/21787ccda9c60578fcf0c7f7b0d06c887b48a343/wandb/data_types.py#L1575)

Converts floating point image on the range [0,1] and integer images
on the range [0,255] to uint8, clipping if necessary.

<a name="wandb.data_types.Image.seq_to_json"></a>
#### seq\_to\_json

```python
 | @classmethod
 | seq_to_json(cls, images, run, key, step)
```

[[source]](https://github.com/wandb/client/blob/21787ccda9c60578fcf0c7f7b0d06c887b48a343/wandb/data_types.py#L1599)

Combines a list of images into a meta dictionary object describing the child images.

<a name="wandb.data_types.JSONMetadata"></a>
## JSONMetadata Objects

```python
class JSONMetadata(Media)
```

[[source]](https://github.com/wandb/client/blob/21787ccda9c60578fcf0c7f7b0d06c887b48a343/wandb/data_types.py#L1718)

JSONMetadata is a type for encoding arbitrary metadata as files.

<a name="wandb.data_types.BoundingBoxes2D"></a>
## BoundingBoxes2D Objects

```python
class BoundingBoxes2D(JSONMetadata)
```

[[source]](https://github.com/wandb/client/blob/21787ccda9c60578fcf0c7f7b0d06c887b48a343/wandb/data_types.py#L1753)

Wandb class for 2D bounding boxes

<a name="wandb.data_types.BoundingBoxes2D.__init__"></a>
#### \_\_init\_\_

```python
 | __init__(val, key, **kwargs)
```

[[source]](https://github.com/wandb/client/blob/21787ccda9c60578fcf0c7f7b0d06c887b48a343/wandb/data_types.py#L1760)

**Arguments**:

- `val` _dict_ - dictionary following the form:
{
- `"class_labels"` - optional mapping from class ids to strings {id: str}
- `"box_data"` - list of boxes: [
{
- `"position"` - {
- `"minX"` - float,
- `"maxX"` - float,
- `"minY"` - float,
- `"maxY"` - float,
},
- `"class_id"` - 1,
- `"box_caption"` - optional str
- `"scores"` - optional dict of scores
},
...
],
}
- `key` _str_ - id for set of bounding boxes

<a name="wandb.data_types.ImageMask"></a>
## ImageMask Objects

```python
class ImageMask(Media)
```

[[source]](https://github.com/wandb/client/blob/21787ccda9c60578fcf0c7f7b0d06c887b48a343/wandb/data_types.py#L1894)

Wandb class for image masks, useful for segmentation tasks

<a name="wandb.data_types.ImageMask.__init__"></a>
#### \_\_init\_\_

```python
 | __init__(val, key, **kwargs)
```

[[source]](https://github.com/wandb/client/blob/21787ccda9c60578fcf0c7f7b0d06c887b48a343/wandb/data_types.py#L1901)

**Arguments**:

- `val` _dict_ - dictionary following 1 of two forms:
{
- `"mask_data"` - 2d array of integers corresponding to classes,
- `"class_labels"` - optional mapping from class ids to strings {id: str}
}

{
- `"path"` - path to an image file containing integers corresponding to classes,
- `"class_labels"` - optional mapping from class ids to strings {id: str}
}
- `key` _str_ - id for set of masks

<a name="wandb.data_types.Plotly"></a>
## Plotly Objects

```python
class Plotly(Media)
```

[[source]](https://github.com/wandb/client/blob/21787ccda9c60578fcf0c7f7b0d06c887b48a343/wandb/data_types.py#L2035)

Wandb class for plotly plots.

**Arguments**:

- `val` - matplotlib or plotly figure

<a name="wandb.data_types.Graph"></a>
## Graph Objects

```python
class Graph(Media)
```

[[source]](https://github.com/wandb/client/blob/21787ccda9c60578fcf0c7f7b0d06c887b48a343/wandb/data_types.py#L2082)

Wandb class for graphs

This class is typically used for saving and diplaying neural net models.  It
represents the graph as an array of nodes and edges.  The nodes can have
labels that can be visualized by wandb.

**Examples**:

Import a keras model:
```
Graph.from_keras(keras_model)
```


**Attributes**:

- `format` _string_ - Format to help wandb display the graph nicely.
- `nodes` _[wandb.Node]_ - List of wandb.Nodes
- `nodes_by_id` _dict_ - dict of ids -> nodes
edges ([(wandb.Node, wandb.Node)]): List of pairs of nodes interpreted as edges
- `loaded` _boolean_ - Flag to tell whether the graph is completely loaded
- `root` _wandb.Node_ - root node of the graph

<a name="wandb.data_types.Node"></a>
## Node Objects

```python
class Node(WBValue)
```

[[source]](https://github.com/wandb/client/blob/21787ccda9c60578fcf0c7f7b0d06c887b48a343/wandb/data_types.py#L2243)

Node used in `Graph`

<a name="wandb.data_types.Node.id"></a>
#### id

```python
 | @property
 | id()
```

[[source]](https://github.com/wandb/client/blob/21787ccda9c60578fcf0c7f7b0d06c887b48a343/wandb/data_types.py#L2295)

Must be unique in the graph

<a name="wandb.data_types.Node.name"></a>
#### name

```python
 | @property
 | name()
```

[[source]](https://github.com/wandb/client/blob/21787ccda9c60578fcf0c7f7b0d06c887b48a343/wandb/data_types.py#L2305)

Usually the type of layer or sublayer

<a name="wandb.data_types.Node.class_name"></a>
#### class\_name

```python
 | @property
 | class_name()
```

[[source]](https://github.com/wandb/client/blob/21787ccda9c60578fcf0c7f7b0d06c887b48a343/wandb/data_types.py#L2315)

Usually the type of layer or sublayer

<a name="wandb.data_types.Node.size"></a>
#### size

```python
 | @size.setter
 | size(val)
```

[[source]](https://github.com/wandb/client/blob/21787ccda9c60578fcf0c7f7b0d06c887b48a343/wandb/data_types.py#L2347)

Tensor size

<a name="wandb.data_types.Node.output_shape"></a>
#### output\_shape

```python
 | @output_shape.setter
 | output_shape(val)
```

[[source]](https://github.com/wandb/client/blob/21787ccda9c60578fcf0c7f7b0d06c887b48a343/wandb/data_types.py#L2357)

Tensor output_shape

<a name="wandb.data_types.Node.is_output"></a>
#### is\_output

```python
 | @is_output.setter
 | is_output(val)
```

[[source]](https://github.com/wandb/client/blob/21787ccda9c60578fcf0c7f7b0d06c887b48a343/wandb/data_types.py#L2367)

Tensor is_output

<a name="wandb.data_types.Node.num_parameters"></a>
#### num\_parameters

```python
 | @num_parameters.setter
 | num_parameters(val)
```

[[source]](https://github.com/wandb/client/blob/21787ccda9c60578fcf0c7f7b0d06c887b48a343/wandb/data_types.py#L2377)

Tensor num_parameters

<a name="wandb.data_types.Node.child_parameters"></a>
#### child\_parameters

```python
 | @child_parameters.setter
 | child_parameters(val)
```

[[source]](https://github.com/wandb/client/blob/21787ccda9c60578fcf0c7f7b0d06c887b48a343/wandb/data_types.py#L2387)

Tensor child_parameters

<a name="wandb.data_types.Node.is_constant"></a>
#### is\_constant

```python
 | @is_constant.setter
 | is_constant(val)
```

[[source]](https://github.com/wandb/client/blob/21787ccda9c60578fcf0c7f7b0d06c887b48a343/wandb/data_types.py#L2397)

Tensor is_constant

<a name="wandb.data_types.Edge"></a>
## Edge Objects

```python
class Edge(WBValue)
```

[[source]](https://github.com/wandb/client/blob/21787ccda9c60578fcf0c7f7b0d06c887b48a343/wandb/data_types.py#L2420)

Edge used in `Graph`

<a name="wandb.data_types.Edge.name"></a>
#### name

```python
 | @property
 | name()
```

[[source]](https://github.com/wandb/client/blob/21787ccda9c60578fcf0c7f7b0d06c887b48a343/wandb/data_types.py#L2442)

Optional, not necessarily unique

<a name="wandb.data_types.data_frame_to_json"></a>
#### data\_frame\_to\_json

```python
data_frame_to_json(df, run, key, step)
```

[[source]](https://github.com/wandb/client/blob/21787ccda9c60578fcf0c7f7b0d06c887b48a343/wandb/data_types.py#L2576)

!NODOC Encode a Pandas DataFrame into the JSON/backend format.

Writes the data to a file and returns a dictionary that we use to represent
it in `Summary`'s.

**Arguments**:

- `df` _pandas.DataFrame_ - The DataFrame. Must not have columns named
"wandb_run_id" or "wandb_data_frame_id". They will be added to the
DataFrame here.
- `run` _wandb_run.Run_ - The Run the DataFrame is associated with. We need
this because the information we store on the DataFrame is derived
from the Run it's in.
- `key` _str_ - Name of the DataFrame, ie. the summary key path in which it's
stored. This is for convenience, so people exploring the
directory tree can have some idea of what is in the Parquet files.
- `step` - History step or "summary".


**Returns**:

A dict representing the DataFrame that we can store in summaries or
histories. This is the format:
{
- `'_type'` - 'data-frame',
# Magic field that indicates that this object is a data frame as
# opposed to a normal dictionary or anything else.
- `'id'` - 'asdf',
# ID for the data frame that is unique to this Run.
- `'format'` - 'parquet',
# The file format in which the data frame is stored. Currently can
# only be Parquet.
- `'project'` - 'wfeas',
# (Current) name of the project that this Run is in. It'd be
# better to store the project's ID because we know it'll never
# change but we don't have that here. We store this just in
# case because we use the project name in identifiers on the
# back end.
- `'path'` - 'media/data_frames/sdlk.parquet',
# Path to the Parquet file in the Run directory.
}

