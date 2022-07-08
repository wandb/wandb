"""test run.save() functionality

---
id: 0.save.glob
plugin:
  - wandb
assert:
  - :wandb:runs_len: 2
  - :wandb:runs[0][config]: {id: save_glob}
  - :wandb:runs[0][files][newdir/newfile1.txt][size]: 4
  - :wandb:runs[0][files][newdir/newfile3.txt][size]: 4
  - :op:not_contains:
    - :wandb:runs[0][files]
    - newdir/newfile.csv
  - :wandb:runs[0][exitcode]: 0
  - :wandb:runs[1][config]: {id: save_glob_later}
  - :wandb:runs[1][files][newdir/newfile1.txt][size]: 4
  - :op:not_contains:
    - :wandb:runs[1][files]
    - newdir/newfile3.txt
  - :op:not_contains:
    - :wandb:runs[1][files]
    - newdir/newfile.csv
  - :wandb:runs[1][exitcode]: 0
"""

import os
import tempfile

import wandb


def write_file(fname):
    with open(fname, "w") as fp:
        fp.write("data")


def test_save_glob():
    with tempfile.TemporaryDirectory() as tmpdir:
        dirname = os.path.join(tmpdir, "newdir")
        glob = os.path.join(dirname, "*.txt")
        os.mkdir(dirname)
        write_file(os.path.join(tmpdir, "newdir", "newfile1.txt"))
        write_file(os.path.join(tmpdir, "newdir", "newfile2.csv"))
        write_file(os.path.join(tmpdir, "newdir", "newfile3.txt"))
        with wandb.init() as run:
            run.config.id = "save_glob"
            run.save(glob, base_path=tmpdir)


def test_save_glob_later():
    """If you add files later, wandb.save() does not pick them up"""
    with tempfile.TemporaryDirectory() as tmpdir:
        dirname = os.path.join(tmpdir, "newdir")
        glob = os.path.join(dirname, "*.txt")
        os.mkdir(dirname)
        write_file(os.path.join(tmpdir, "newdir", "newfile1.txt"))
        with wandb.init() as run:
            run.config.id = "save_glob_later"
            run.save(glob, base_path=tmpdir)
            write_file(os.path.join(tmpdir, "newdir", "newfile2.csv"))
            write_file(os.path.join(tmpdir, "newdir", "newfile3.txt"))


def main():
    test_save_glob()
    test_save_glob_later()


if __name__ == "__main__":
    main()
