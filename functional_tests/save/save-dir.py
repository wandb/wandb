"""test run.save() functionality

---
id: 0.save.dir
plugin:
  - wandb
assert:
  - :wandb:runs_len: 1
  - :wandb:runs[0][config]: {id: save_dir}
  - :op:not_contains:
    - :wandb:runs[0][files]
    - newdir/newfile.txt
  - :wandb:runs[0][exitcode]: 0
"""

import os
import tempfile

import wandb


def write_file(fname):
    with open(fname, "w") as fp:
        fp.write("data")


def test_save_dir():
    """NOTE: this is demonstrating broken functionality."""
    with tempfile.TemporaryDirectory() as tmpdir:
        dirname = os.path.join(tmpdir, "newdir")
        fname = os.path.join(tmpdir, "newdir", "newfile.txt")
        os.mkdir(dirname)
        write_file(fname)
        with wandb.init() as run:
            run.config.id = "save_dir"
            run.save(dirname, base_path=tmpdir)


def main():
    test_save_dir()


if __name__ == "__main__":
    main()
