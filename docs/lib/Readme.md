# Important Files
- `docgen.py`: Generic documentation generator for wandb
- `docgen_cli.py`: Documentation generator for wandb CLI
- `wandb.yaml`: The `yaml` file to configure the settings provided to `docgen.py`

## docgen.py
**Usage**
```bash
$ python docgen.py [yaml file] [template file]

[yaml file]- wandb.yaml
[template file]- template/template.md
```

**Outputs**
A folder named `docs` in the same folder as the code. The files in the `docs` folder are the generated markdown.

**Requirements**
- [mydocstring](https://github.com/ooreilly/mydocstring)

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

## Folders in the directory
- utils- Utility modules for `docgen.py`
- template- Template markdown for the documentation
