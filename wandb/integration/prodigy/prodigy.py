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


def _named_entity(docs):
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

def upload_dataset(dataset):
    # Check if wandb.init has been called
    if wandb.run is None:
        raise ValueError("You must call wandb.init() before upload_dataset()")

    # Retrieve prodigy dataset
    database = connect()
    data = database.get_dataset(dataset)

    table_df = pd.DataFrame(data)
    columns = list(table_df.columns)
    main_table = wandb.Table(dataframe=table_df)
    wandb.log({"dataset": main_table})

