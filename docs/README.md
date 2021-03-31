# Important Files
- `generate.py`: Generic documentation generator for wandb
- `docgen_cli.py`: Documentation generator for wandb CLI

## generate.py
The follwing is a road map of how to generate documentaion like tensorflow.
**Steps**
1. `pip install git+https://github.com/ariG23498/docs@wandb-docs` This installs the modified `tensorflow_docs`. The modifications are minor templating changes.
3. `python generate.py` creates the documentation.

**Outputs**
A folder named `library` in the same folder as the code. The files in the `library` folder are the generated markdown.

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
