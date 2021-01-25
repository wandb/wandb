"""A tool to generate api_docs for wandb

```
python generate.py
```

Requires a local installation of `tensorflow_docs`:

```
pip install git+https://github.com/ariG23498/docs
```
"""
import pathlib
from os import path

import wandb

from tensorflow_docs.api_generator import doc_controls
from tensorflow_docs.api_generator import generate_lib

def build_docs(name_pair,output_dir,code_url_prefix, search_hints, gen_report):
    """Build api docs for w&b.
    
    Args:
        name_pair: Name of the pymodule
        output_dir: A string path, where to put the files.
        code_url_prefix: prefix for "Defined in" links.
        search_hints: Bool. Include meta-data search hints at the top of each file.
        gen_report: Bool. Generates an API report containing the health of the
            docstrings of the public API.
    """
    for cls in [wandb.data_types.WBValue, wandb.data_types.Media, wandb.data_types.BatchableMedia]:
        doc_controls.decorate_all_class_attributes(
            decorator=doc_controls.do_not_doc_in_subclasses,
            cls=cls,
            skip=["__init__"])

    doc_generator = generate_lib.DocGenerator(
        root_title="W&B",
        py_modules=[name_pair],
        base_dir=path.dirname(wandb.__file__),
        search_hints=search_hints,
        code_url_prefix=code_url_prefix,
        site_path="",
        gen_report=gen_report,
        yaml_toc=False)

    doc_generator.build(output_dir)


if __name__== "__main__":
    CODE_URL_PREFIX = "https://www.github.com/wandb/client/tree/master/wandb"
    wandb_methods = [
        'init',
        'log',
        'config',
        'summary',
        'login',
        'agent',
        'save',
        'finish',]

    wandb_classes = [
        'Api',]

    wandb.__all__ = wandb_methods+wandb_classes

    build_docs(
        name_pair=("wandb", wandb),
        output_dir="API Reference",
        code_url_prefix=CODE_URL_PREFIX,
        search_hints=False,
        gen_report=False)
    
    wandb_datatypes = [
        'Image',
        'Plotly',
        'Video',
        'Audio',
        'Table',
        'Html',
        'Object3D',
        'Molecule',
        'Histogram',]

    wandb.__all__ = wandb_datatypes

    build_docs(
        name_pair=("datatypes",wandb),
        output_dir="API Reference/wandb",
        code_url_prefix=CODE_URL_PREFIX,
        search_hints=False,
        gen_report=False)