# Docs

We publish these documents in gitbook at our offial [documentation site](https://docs.wandb.com)

You can view latest docs on a given branch directly on github [here](docs/markdown)

# Development

We based our doc generation on https://github.com/NiklasRosenstein/pydoc-markdown.

Running `python generate.py` will generate the markdown docs in the markdown folder.

I really hacked together a bunch of additions by monkeypatching pydoc-markdown. You can customize the generator by monkeying around with the Section class in generate.py or google_parser.py which are not pretty.
