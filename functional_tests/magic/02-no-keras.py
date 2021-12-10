#!/usr/bin/env python
"""magic test with no ml modules installed.

---
id: 0.magic.02-no-keras
plugin:
  - wandb
tag:
  shard: noml
command:
    args:
        - --layers=5
assert:
  - :wandb:runs_len: 1
  - :wandb:runs[0][config][epochs]: 4
  - :wandb:runs[0][config][layers]: 5
  - :wandb:runs[0][exitcode]: 0
"""

import argparse
import sys

from wandb import magic  # noqa: F401


def train(layers, epochs):
    for n in range(layers or 10):
        print(f"Layer: {n}")
    for n in range(epochs or 10):
        print(f"Epoch: {n}")


def main():
    assert "tensorflow" not in sys.modules
    parser = argparse.ArgumentParser()
    parser.add_argument("--layers", type=int, help="num layers")
    parser.add_argument("--epochs", type=int, default=4, help="num epochs")
    args = parser.parse_args()
    train(args.layers, args.epochs)


if __name__ == "__main__":
    main()
