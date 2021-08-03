import collections
from copy import deepcopy
import spacy
import pandas as pd
import wandb
from wandb import util
from wandb.plots.utils import (
    test_missing,
    deprecation_notice,
)

try:
    from prodigy.components.db import connect
except:
    print("Warning: `prodigy` is required but not installed.")


def named_entity(docs):
    deprecation_notice()

    spacy = util.get_module(
        "spacy",
        required="part_of_speech requires the spacy library, install with `pip install spacy`",
    )
    en_core_web_md = util.get_module(
        "en_core_web_md",
        required="part_of_speech requires the en_core_web_md library, install with `python -m spacy download en_core_web_md`",
    )

    if test_missing(docs=docs):
        wandb.termlog("Visualizing named entity recognition.")
        html = spacy.displacy.render(
            docs, style="ent", page=True, minify=True, jupyter=False
        )
        wandb_html = wandb.Html(html)
        return wandb_html


def merge(dict1, dict2):
    ''' Return a new dictionary by merging two dictionaries recursively. '''
    result = deepcopy(dict1)

    for key, value in dict2.items():
        if isinstance(value, collections.Mapping):
            result[key] = merge(result.get(key, {}), value)
        else:
            result[key] = deepcopy(dict2[key])

    return result


def get_keys(list_data_dict, struct):
    # Get the structure of the JSON objects in the database
    # This is similar to getting a JSON schema but with slightly different format
    for i, item in enumerate(list_data_dict):
        for k, v in item.items():
            # Check if key already exists in template
            if not k in struct.keys():
                if isinstance(v, list):
                    struct[k] = {}
                    struct[k] = get_keys(v, struct[k])
                elif isinstance(v, dict):
                    struct[k] = {}
                    struct[k] = get_keys([v], struct[k])
                else:
                    struct[k] = type(v)
            else:
                # Get the value of struct[k] which is the current template
                # Find new keys and then merge the two templates together
                cur_struct = struct[k]
                if isinstance(v, list):
                    struct[k] = {}
                    struct[k] = get_keys(v, struct[k])
                    # merge cur_struct and struct[k], remove duplicates
                    struct[k] = merge(struct[k], cur_struct)
                elif isinstance(v, dict):
                    struct[k] = {}
                    struct[k] = get_keys([v], struct[k])
                    # merge cur_struct and struct[k], remove duplicates
                    struct[k] = merge(struct[k], cur_struct)
                else:
                    # if the type of field k is currently NoneType, then update
                    if (struct[k] == type(None)) or (v is not None):
                        struct[k] = type(v)
    return struct

def standardize(item, structure):
    for k, v in structure.items():
        if k not in item:
            # If the structure/field does not exist
            if isinstance(v, dict):
                # If key k is not a singular value
                item[k] = None
            else:
                # Assign a default type
                item[k] = v()
        else:
            # If the structure/field already exists and is a list or dict
            if isinstance(item[k], list):
                for subitem in item[k]:
                    standardize(subitem, v)
            elif isinstance(item[k], dict):
                standardize(item[k], v)


def create_table(data):
    # create table object from columns
    table_df = pd.DataFrame(data)
    columns = list(table_df.columns)
    if "spans" in table_df.columns:
        columns.append('spans_visual')
    main_table = wandb.Table(columns=columns)

    # Convert to dictionary format to maintain order during processing
    matrix = table_df.to_dict(orient="records")


    nlp = spacy.load("en_core_web_md", disable=['ner'])

    for i, document in enumerate(matrix):
        if "spans_visual" in columns:
            # Add visuals for spans
            document["spans_visual"] = None
            doc = nlp(document["text"])
            ents = []
            if ("spans" in document) and (document["spans"] is not None):
                for span in document["spans"]:
                    charspan = doc.char_span(span["start"], span["end"], span["label"])
                    ents.append(charspan)
                doc.ents = ents
                document["spans_visual"] = named_entity(docs=doc)

        # Create row and append to table
        values_list = list(document.values())
        main_table.add_data(*values_list)
    return main_table

def upload_dataset(dataset_name):
    # Check if wandb.init has been called
    if wandb.run is None:
        raise ValueError("You must call wandb.init() before upload_dataset()")

    # Retrieve prodigy dataset
    database = connect()
    data = database.get_dataset(dataset_name)
    schema = get_keys(data, {})
    for i, d in enumerate(data):
        standardize(data[i], schema)
    table = create_table(data)
    wandb.log({dataset_name: table})
    print("Prodigy dataset `" + dataset_name + "` uploaded.")



