#!/usr/bin/env python
"""Test spaCy integration
---
id: 0.0.4
check-ext-wandb: {}
assert:
  - :wandb:runs_len: 3
  - :wandb:runs[0][project]: IMDB_sentiment
  - :wandb:runs[0][config][training.batcher.size.start]: 100
  - :wandb:runs[0][summary][acc]: 1.0
  - :wandb:runs[0][exitcode]: 0
  - :wandb:runs[1][config][test]: 123
  - :wandb:runs[1][exitcode]: 0
  - :wandb:runs[2][exitcode]: 0
"""
import os

os.system("spacy project clone integrations/wandb")
os.system("cd wandb && spacy project assets && spacy project run log")