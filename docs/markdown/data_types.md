---
description: wandb.data_types
---

# wandb.data_types
[source](https://github.com/wandb/client/blob/master/wandb/data_types.py#L0)
Wandb has special data types for logging rich visualizations.

All of the special data types are subclasses of WBValue. All of the data types serialize to JSON, since that is what wandb uses to save the objects locally and upload them to the W&B server.


## WBValue
[source](https://github.com/wandb/client/blob/master/wandb/data_types.py#L40)
```python
WBValue(self)
```
Abstract parent class for things that can be logged by wandb.log() and visualized by wandb.

The objects will be serialized as JSON and always have a _type attribute that indicates how to interpret the other fields.

**Returns**:

 JSON-friendly `dict` representation of this object that can later be serialized to a string.
 

## Histogram
[source](https://github.com/wandb/client/blob/master/wandb/data_types.py#L59)
```python
Histogram(self, sequence=None, np_histogram=None, num_bins=64)
```

wandb class for histograms

This object works just like numpy's histogram function https://docs.scipy.org/doc/numpy/reference/generated/numpy.histogram.html

**Examples**:

 Generate histogram from a sequence
```python
wandb.Histogram([1,2,3])
```
 
 Efficiently initialize from np.histogram.
```python
hist = np.histogram(data)
wandb.Histogram(np_histogram=hist)
```
 

**Arguments**:

- `sequence` _array_like_ - input data for histogram
- `np_histogram` _numpy histogram_ - alternative input of a precoomputed histogram
- `num_bins` _int_ - Number of bins for the histogram.  The default number of bins is 64.  The maximum number of bins is 512
 

**Attributes**:

- `bins` _[float]_ - edges of bins
- `histogram` _[int]_ - number of elements falling in each bin
 

## Table
[source](https://github.com/wandb/client/blob/master/wandb/data_types.py#L117)
```python
Table(self, columns=['Input', 'Output', 'Expected'], data=None, rows=None)
```
This is a table designed to display small sets of records.

**Arguments**:

- `columns` _[str]_ - Names of the columns in the table. Defaults to ["Input", "Output", "Expected"].
- `data` _array_ - 2D Array of values that will be displayed as strings.
 

## Media
[source](https://github.com/wandb/client/blob/master/wandb/data_types.py#L150)
```python
Media(self, path, is_tmp=False, extension=None)
```
A WBValue that we store as a file outside JSON and show in a media panel on the front end.

If necessary, we move or copy the file into the Run's media directory so that it gets uploaded.


## BatchableMedia
[source](https://github.com/wandb/client/blob/master/wandb/data_types.py#L243)
```python
BatchableMedia(self, path, is_tmp=False, extension=None)
```
Parent class for Media we treat specially in batches, like images and thumbnails.

Apart from images, we just use these batches to help organize files by name in the media directory.


## Audio
[source](https://github.com/wandb/client/blob/master/wandb/data_types.py#L255)
```python
Audio(self, data_or_path, sample_rate=None, caption=None)
```

Wandb class for audio clips.

**Arguments**:

- `data_or_path` _string or numpy array_ - A path to an audio file or a numpy array of audio data.
- `sample_rate` _int_ - Sample rate, required when passing in raw numpy array of audio data.
- `caption` _string_ - Caption to display with audio.
 

## Object3D
[source](https://github.com/wandb/client/blob/master/wandb/data_types.py#L352)
```python
Object3D(self, data_or_path, **kwargs)
```

Wandb class for 3D point clouds.

**Arguments**:

 data_or_path (numpy array | string | io ): Object3D can be initialized from a file or a numpy array.
 
 The file types supported are obj, gltf, babylon, stl.  You can pass a path to a file or an io object and a file_type which must be one of `'obj', 'gltf', 'babylon', 'stl'`.
 
 The shape of the numpy array must be one of either:
```python
[[x y z],       ...] nx3
[x y z c],     ...] nx4 where c is a category with supported range [1, 14]
[x y z r g b], ...] nx4 where is rgb is color
```
 
 

## Html
[source](https://github.com/wandb/client/blob/master/wandb/data_types.py#L458)
```python
Html(self, data, inject=True)
```

Wandb class for arbitrary html

**Arguments**:

- `data` _string or io object_ - HTML to display in wandb
- `inject` _boolean_ - Add a stylesheet to the HTML object.  If set to False the HTML will pass through unchanged.
 

## Video
[source](https://github.com/wandb/client/blob/master/wandb/data_types.py#L524)
```python
Video(self, data_or_path, caption=None, fps=4, format=None)
```

Wandb representation of video.

**Arguments**:

 data_or_path (numpy array | string | io): Video can be initialized with a path to a file or an io object. The format must be "gif", "mp4", "webm" or "ogg". The format must be specified with the format argument. Video can be initialized with a numpy tensor. The numpy tensor must be either 4 dimensional or 5 dimensional. Channels should be (time, channel, height, width) or (batch, time, channel, height width)
- `caption` _string_ - caption associated with the video for display
- `fps` _int_ - frames per second for video. Default is 4.
- `format` _string_ - format of video, necessary if initializing with path or io object.
 

## Image
[source](https://github.com/wandb/client/blob/master/wandb/data_types.py#L667)
```python
Image(self, data_or_path, mode=None, caption=None, grouping=None)
```

Wandb class for images.

**Arguments**:

- `data_or_path` _numpy array | string | io_ - Accepts numpy array of image data, or a PIL image. The class attempts to infer the data format and converts it.
- `mode` _string_ - The PIL mode for an image. Most common are "L", "RGB", "RGBA". Full explanation at https://pillow.readthedocs.io/en/4.2.x/handbook/concepts.html#concept-modes.
- `caption` _string_ - Label for display of image.
 

## Graph
[source](https://github.com/wandb/client/blob/master/wandb/data_types.py#L837)
```python
Graph(self, format='keras')
```
Wandb class for graphs

This class is typically used for saving and diplaying neural net models.  It represents the graph as an array of nodes and edges.  The nodes can have labels that can be visualized by wandb.

**Examples**:

 Import a keras model:
```python
Graph.from_keras(keras_model)
```
 

**Attributes**:

- `format` _string_ - Format to help wandb display the graph nicely.
- `nodes` _[wandb.Node]_ - List of wandb.Nodes
- `nodes_by_id` _dict_ - dict of ids -> nodes edges ([(wandb.Node, wandb.Node)]): List of pairs of nodes interpreted as edges
- `loaded` _boolean_ - Flag to tell whether the graph is completely loaded
- `root` _wandb.Node_ - root node of the graph
 

## Node
[source](https://github.com/wandb/client/blob/master/wandb/data_types.py#L971)
```python
Node(self,
     id=None,
     name=None,
     class_name=None,
     size=None,
     parameters=None,
     output_shape=None,
     is_output=None,
     num_parameters=None,
     node=None)
```

Node used in [`Graph`](#graph)


## Edge
[source](https://github.com/wandb/client/blob/master/wandb/data_types.py#L1136)
```python
Edge(self, from_node, to_node)
```

Edge used in [`Graph`](#graph)


## data_types.plot_to_json
[source](https://github.com/wandb/client/blob/master/wandb/data_types.py#L1266)
```python
plot_to_json(obj)
```
Converts a matplotlib or plotly object to json so that we can pass it the the wandb server and display it nicely there

## data_types.data_frame_to_json
[source](https://github.com/wandb/client/blob/master/wandb/data_types.py#L1281)
```python
data_frame_to_json(df, run, key, step)
```
Encode a Pandas DataFrame into the JSON/backend format.

Writes the data to a file and returns a dictionary that we use to represent it in `Summary`'s.

**Arguments**:

- `df` _pandas.DataFrame_ - The DataFrame. Must not have columns named "wandb_run_id" or "wandb_data_frame_id". They will be added to the DataFrame here.
- `run` _wandb_run.Run_ - The Run the DataFrame is associated with. We need this because the information we store on the DataFrame is derived from the Run it's in.
- `key` _str_ - Name of the DataFrame, ie. the summary key path in which it's stored. This is for convenience, so people exploring the directory tree can have some idea of what is in the Parquet files.
- `step` - History step or "summary".
 

**Returns**:

 A dict representing the DataFrame that we can store in summaries or histories. This is the format: {
- `'_type'` - 'data-frame', # Magic field that indicates that this object is a data frame as # opposed to a normal dictionary or anything else.
- `'id'` - 'asdf', # ID for the data frame that is unique to this Run.
- `'format'` - 'parquet', # The file format in which the data frame is stored. Currently can # only be Parquet.
- `'project'` - 'wfeas', # (Current) name of the project that this Run is in. It'd be # better to store the project's ID because we know it'll never # change but we don't have that here. We store this just in # case because we use the project name in identifiers on the # back end.
- `'path'` - 'media/data_frames/sdlk.parquet', # Path to the Parquet file in the Run directory. }
 
