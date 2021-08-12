#!/usr/bin/env python
"""Test prodigy integration

---
id: 6.0.1
name: prodigy integration test
tag:
  suite: nightly
command:
  timeout: 500
plugin:
  - wandb
depend:
  requirements:
    - wandb
    - spacy
    - https://github.com/explosion/spacy-models/releases/download/en_core_web_md-3.0.0/en_core_web_md-3.0.0.tar.gz#egg=en_core_web_md
  files:
    - file: prodigy_test_resources.zip
      source: https://raw.githubusercontent.com/wandb/wandb-testing/master/test_data/prodigy/prodigy_test_resources.zip
assert:
  - :wandb:runs_len: 1
  - :wandb:runs[0][summary]:
      image_segmentation[nrows]: 34
      audio[nrows]: 3
      nyt_tokens[nrows]: 200
      quora_questions[nrows]: 100
      already_labelled[nrows]: 373
      products_html[nrows]: 200
      unsplash_base64[nrows]: 207
      unsplash_base64_corrupted[nrows]: 1
      chinese_chars[nrows]: 30
      unsplash[nrows]: 210
      movies_ner[nrows]: 0
      movies_tokens[nrows]: 200
      nyt_classification[nrows]: 200
      unsplash_food_options[nrows]: 37
      videos[nrows]: 3
      nyt_text[nrows]: 200
      movies_cats[nrows]: 200
      nyt_pos_tokens[nrows]: 246
      compare_medical[nrows]: 300
      nyt_ner[nrows]: 282
      bio_tokens[nrows]: 129
      bad_encoding[nrows]: 20
      nyt_dep[nrows]: 112
  - :wandb:runs[0][exitcode]: 0
"""

import os
import sys
from unittest.mock import Mock
from zipfile import ZipFile

from prodigy_connect import Connect
import wandb
from wandb.integration.prodigy import upload_dataset

sys.modules['prodigy'] = Mock()
sys.modules['prodigy.components'] = Mock()
sys.modules['prodigy.components.db'] = Connect()

# Extract test dataset files downloaded by "yea"
with ZipFile('prodigy_test_resources.zip', 'r') as zip_obj:
    zip_obj.extractall()

# Test upload each dataset
run = wandb.init(project='prodigy')
all_files = os.listdir("prodigy_test_resources")
for dataset in all_files:
    dataset_name = dataset.split(".")[0]  # remove .json
    upload_dataset(dataset_name)
wandb.finish()
