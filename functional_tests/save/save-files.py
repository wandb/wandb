"""test run.save() functionality

---
id: 0.save.files
plugin:
  - wandb
assert:
  - :wandb:runs_len: 2
  - :wandb:runs[0][config]: {id: save_file}
  - :wandb:runs[0][files][newfile.txt][size]: 4
  - :wandb:runs[0][exitcode]: 0
  - :wandb:runs[1][config]: {id: save_file_in_dir}
  - :wandb:runs[1][files][newdir/newfile.txt][size]: 4
  - :wandb:runs[1][exitcode]: 0
"""

import os
import tempfile

import wandb


def write_file(fname):
    with open(fname, "w") as fp:
        fp.write("data")


def test_save_file():
    with tempfile.TemporaryDirectory() as tmpdir:
        fname = os.path.join(tmpdir, "newfile.txt")
        write_file(fname)
        with wandb.init() as run:
            run.config.id = "save_file"
            run.save(fname, base_path=tmpdir)


def test_save_file_in_dir():
    with tempfile.TemporaryDirectory() as tmpdir:
        dirname = os.path.join(tmpdir, "newdir")
        fname = os.path.join(tmpdir, "newdir", "newfile.txt")
        os.mkdir(dirname)
        write_file(fname)
        with wandb.init() as run:
            run.config.id = "save_file_in_dir"
            run.save(fname, base_path=tmpdir)


def main():
    test_save_file()
    test_save_file_in_dir()


if __name__ == "__main__":
    main()
