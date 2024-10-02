"""Prodigy integration for W&B.

User can upload Prodigy annotated datasets directly
from the local database to W&B in Tables format.

Example usage:

```python
import wandb
from wandb.integration.prodigy import upload_dataset

run = wandb.init(project="prodigy")
upload_dataset("name_of_dataset")
wandb.finish()
```
"""

import base64
import collections.abc
import io
import urllib
from copy import deepcopy

import pandas as pd
from PIL import Image

import wandb
from wandb import util
from wandb.plot.utils import test_missing
from wandb.sdk.lib import telemetry as wb_telemetry


def named_entity(docs):
    """Create a named entity visualization.

    Taken from https://github.com/wandb/wandb/blob/main/wandb/plots/named_entity.py.
    """
    spacy = util.get_module(
        "spacy",
        required="part_of_speech requires the spacy library, install with `pip install spacy`",
    )

    util.get_module(
        "en_core_web_md",
        required="part_of_speech requires `en_core_web_md` library, install with `python -m spacy download en_core_web_md`",
    )

    # Test for required packages and missing & non-integer values in docs data
    if test_missing(docs=docs):
        html = spacy.displacy.render(
            docs, style="ent", page=True, minify=True, jupyter=False
        )
        wandb_html = wandb.Html(html)
        return wandb_html


def merge(dict1, dict2):
    """Return a new dictionary by merging two dictionaries recursively."""
    result = deepcopy(dict1)

    for key, value in dict2.items():
        if isinstance(value, collections.abc.Mapping):
            result[key] = merge(result.get(key, {}), value)
        else:
            result[key] = deepcopy(dict2[key])

    return result


def get_schema(list_data_dict, struct, array_dict_types):
    """Get a schema of the dataset's structure and data types."""
    # Get the structure of the JSON objects in the database
    # This is similar to getting a JSON schema but with slightly different format
    for _i, item in enumerate(list_data_dict):
        # If the list contains dict objects
        for k, v in item.items():
            # Check if key already exists in template
            if k not in struct.keys():
                if isinstance(v, list):
                    if len(v) > 0 and isinstance(v[0], list):
                        # nested list structure
                        struct[k] = type(v)  # type list
                    elif len(v) > 0 and not (
                        isinstance(v[0], list) or isinstance(v[0], dict)
                    ):
                        # list of singular values
                        struct[k] = type(v)  # type list
                    else:
                        # list of dicts
                        array_dict_types.append(
                            k
                        )  # keep track of keys that are type list[dict]
                        struct[k] = {}
                        struct[k] = get_schema(v, struct[k], array_dict_types)
                elif isinstance(v, dict):
                    struct[k] = {}
                    struct[k] = get_schema([v], struct[k], array_dict_types)
                else:
                    struct[k] = type(v)
            else:
                # Get the value of struct[k] which is the current template
                # Find new keys and then merge the two templates together
                cur_struct = struct[k]
                if isinstance(v, list):
                    if len(v) > 0 and isinstance(v[0], list):
                        # nested list coordinate structure
                        # if the value in the item is currently None, then update
                        if v is not None:
                            struct[k] = type(v)  # type list
                    elif len(v) > 0 and not (
                        isinstance(v[0], list) or isinstance(v[0], dict)
                    ):
                        # single list with values
                        # if the value in the item is currently None, then update
                        if v is not None:
                            struct[k] = type(v)  # type list
                    else:
                        array_dict_types.append(
                            k
                        )  # keep track of keys that are type list[dict]
                        struct[k] = {}
                        struct[k] = get_schema(v, struct[k], array_dict_types)
                        # merge cur_struct and struct[k], remove duplicates
                        struct[k] = merge(struct[k], cur_struct)
                elif isinstance(v, dict):
                    struct[k] = {}
                    struct[k] = get_schema([v], struct[k], array_dict_types)
                    # merge cur_struct and struct[k], remove duplicates
                    struct[k] = merge(struct[k], cur_struct)
                else:
                    # if the value in the item is currently None, then update
                    if v is not None:
                        struct[k] = type(v)

    return struct


def standardize(item, structure, array_dict_types):
    """Standardize all rows/entries in dataset to fit the schema.

    Will look for missing values and fill it in so all rows have
    the same items and structure.
    """
    for k, v in structure.items():
        if k not in item:
            # If the structure/field does not exist
            if isinstance(v, dict) and (k not in array_dict_types):
                # If key k is of type dict, and not not a type list[dict]
                item[k] = {}
                standardize(item[k], v, array_dict_types)
            elif isinstance(v, dict) and (k in array_dict_types):
                # If key k is of type dict, and is actually of type list[dict],
                # just treat as a list and set to None by default
                item[k] = None
            else:
                # Assign a default type
                item[k] = v()
        else:
            # If the structure/field already exists and is a list or dict
            if isinstance(item[k], list):
                # ignore if item is a nested list structure or list of non-dicts
                condition = (
                    not (len(item[k]) > 0 and isinstance(item[k][0], list))
                ) and (
                    not (
                        len(item[k]) > 0
                        and not (
                            isinstance(item[k][0], list) or isinstance(item[k][0], dict)
                        )
                    )
                )
                if condition:
                    for sub_item in item[k]:
                        standardize(sub_item, v, array_dict_types)
            elif isinstance(item[k], dict):
                standardize(item[k], v, array_dict_types)


def create_table(data):
    """Create a W&B Table.

    - Create/decode images from URL/Base64
    - Uses spacy to translate NER span data to visualizations.
    """
    # create table object from columns
    table_df = pd.DataFrame(data)
    columns = list(table_df.columns)
    if ("spans" in table_df.columns) and ("text" in table_df.columns):
        columns.append("spans_visual")
    if "image" in columns:
        columns.append("image_visual")
    main_table = wandb.Table(columns=columns)

    # Convert to dictionary format to maintain order during processing
    matrix = table_df.to_dict(orient="records")

    # Import en_core_web_md if exists
    en_core_web_md = util.get_module(
        "en_core_web_md",
        required="part_of_speech requires `en_core_web_md` library, install with `python -m spacy download en_core_web_md`",
    )
    nlp = en_core_web_md.load(disable=["ner"])

    # Go through each individual row
    for _i, document in enumerate(matrix):
        # Text NER span visualizations
        if ("spans_visual" in columns) and ("text" in columns):
            # Add visuals for spans
            document["spans_visual"] = None
            doc = nlp(document["text"])
            ents = []
            if ("spans" in document) and (document["spans"] is not None):
                for span in document["spans"]:
                    if ("start" in span) and ("end" in span) and ("label" in span):
                        charspan = doc.char_span(
                            span["start"], span["end"], span["label"]
                        )
                        ents.append(charspan)
                doc.ents = ents
                document["spans_visual"] = named_entity(docs=doc)

        # Convert image link to wandb Image
        if "image" in columns:
            # Turn into wandb image
            document["image_visual"] = None
            if ("image" in document) and (document["image"] is not None):
                isurl = urllib.parse.urlparse(document["image"]).scheme in (
                    "http",
                    "https",
                )
                isbase64 = ("data:" in document["image"]) and (
                    ";base64" in document["image"]
                )
                if isurl:
                    # is url
                    try:
                        im = Image.open(urllib.request.urlopen(document["image"]))
                        document["image_visual"] = wandb.Image(im)
                    except urllib.error.URLError:
                        print(
                            "Warning: Image URL "
                            + str(document["image"])
                            + " is invalid."
                        )
                        document["image_visual"] = None
                elif isbase64:
                    # is base64 uri
                    imgb64 = document["image"].split("base64,")[1]
                    try:
                        msg = base64.b64decode(imgb64)
                        buf = io.BytesIO(msg)
                        im = Image.open(buf)
                        document["image_visual"] = wandb.Image(im)
                    except base64.binascii.Error:
                        print(
                            "Warning: Base64 string "
                            + str(document["image"])
                            + " is invalid."
                        )
                        document["image_visual"] = None
                else:
                    # is data path
                    document["image_visual"] = wandb.Image(document["image"])

        # Create row and append to table
        values_list = list(document.values())
        main_table.add_data(*values_list)
    return main_table


def upload_dataset(dataset_name):
    """Upload dataset from local database to Weights & Biases.

    Args:
        dataset_name: The name of the dataset in the Prodigy database.
    """
    # Check if wandb.init has been called
    if wandb.run is None:
        raise ValueError("You must call wandb.init() before upload_dataset()")

    with wb_telemetry.context(run=wandb.run) as tel:
        tel.feature.prodigy = True

    prodigy_db = util.get_module(
        "prodigy.components.db",
        required="`prodigy` library is required but not installed. Please see https://prodi.gy/docs/install",
    )
    # Retrieve and upload prodigy dataset
    database = prodigy_db.connect()
    data = database.get_dataset(dataset_name)

    array_dict_types = []
    schema = get_schema(data, {}, array_dict_types)

    for i, _d in enumerate(data):
        standardize(data[i], schema, array_dict_types)
    table = create_table(data)
    wandb.log({dataset_name: table})
    print("Prodigy dataset `" + dataset_name + "` uploaded.")
