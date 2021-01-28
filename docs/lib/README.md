# Important Files
- `generate.py`: Generic documentation generator for wandb
- `docgen_cli.py`: Documentation generator for wandb CLI

## generate.py
**Usage**
```bash
$ python generate.py
```

**Outputs**
A folder named `docs` in the same folder as the code. The files in the `docs` folder are the generated markdown.

**Requirements**
- tensorflow_docs
- wandb

## docgen_cli.py
**Usage**
```bash
$ python docgen_cli.py
```

**Outputs**
A file named `cli.md` in the same folder as the code. The file is the generated markdown for the CLI.

**Requirements**
- python >= 3.8
- wandb
