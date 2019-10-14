# W&B Docs

We publish master to our offcial [documentation site](https://docs.wandb.com)

You can view our latest docs on a given branch directly on github [here](docs/markdown)

## Development

We based our doc generation on https://github.com/NiklasRosenstein/pydoc-markdown.

Running `python generate.py` will generate the markdown docs in the markdown folder.

We hacked together a bunch of additions by monkeypatching pydoc-markdown. You can customize the generator by monkeying around with the Section class in generate.py or google_parser.py which are not pretty...
