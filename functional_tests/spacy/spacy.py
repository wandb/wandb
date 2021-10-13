"""Tests wandb integration in spaCy"""

import os

os.system("spacy project clone integrations/wandb")
os.system("cd wandb && spacy project assets && spacy project run log")
