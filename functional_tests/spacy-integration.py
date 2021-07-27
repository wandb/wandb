#!/usr/bin/env python
"""Test spaCy integration
---
id: 0.0.4
check-ext-wandb: {}
assert:
  - :wandb:runs_len: 1
  - :wandb:runs[0][project]: IMDB_sentiment
  - :wandb:runs[0][config][training.batcher.size.start]: 100
  - :op:>=:
    - :wandb:runs[0][summary][score]
    - 0.5
  - :wandb:runs[0][exitcode]: 0
"""
import os

os.system("spacy project clone integrations/wandb")
os.system("cd wandb && spacy project assets && spacy project run log")