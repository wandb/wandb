#!/usr/bin/env python
"""Test prodigy integration

---
id: 0.prodigy.1
name: prodigy integration test
command:
  timeout: 300
plugin:
  - wandb
tag:
  skips:
    - platform: win
depend:
  requirements:
    - spacy>=3.0.0,<4.0.0
    - https://github.com/explosion/spacy-models/releases/download/en_core_web_md-3.0.0/en_core_web_md-3.0.0.tar.gz#egg=en_core_web_md
    - Pillow
    - scipy
  files:
    - file: prodigy_test_resources.zip
      source: https://raw.githubusercontent.com/wandb/wandb-testing/master/test_data/prodigy/prodigy_test_resources.zip
assert:
  - :wandb:runs_len: 1
  - :wandb:runs[0][summary][image_segmentation][nrows]: 34
  - :wandb:runs[0][summary][audio][nrows]: 3
  - :wandb:runs[0][summary][nyt_tokens][nrows]: 200
  - :wandb:runs[0][summary][quora_questions][nrows]: 100
  - :wandb:runs[0][summary][already_labelled][nrows]: 373
  - :wandb:runs[0][summary][products_html][nrows]: 200
  - :wandb:runs[0][summary][unsplash_base64][nrows]: 207
  - :wandb:runs[0][summary][unsplash_base64_corrupted][nrows]: 1
  - :wandb:runs[0][summary][chinese_chars][nrows]: 30
  - :wandb:runs[0][summary][unsplash][nrows]: 210
  - :wandb:runs[0][summary][movies_ner][nrows]: 0
  - :wandb:runs[0][summary][movies_tokens][nrows]: 200
  - :wandb:runs[0][summary][nyt_classification][nrows]: 200
  - :wandb:runs[0][summary][unsplash_food_options][nrows]: 37
  - :wandb:runs[0][summary][videos][nrows]: 3
  - :wandb:runs[0][summary][nyt_text][nrows]: 200
  - :wandb:runs[0][summary][movies_cats][nrows]: 200
  - :wandb:runs[0][summary][nyt_pos_tokens][nrows]: 246
  - :wandb:runs[0][summary][compare_medical][nrows]: 300
  - :wandb:runs[0][summary][nyt_ner][nrows]: 282
  - :wandb:runs[0][summary][bio_tokens][nrows]: 129
  - :wandb:runs[0][summary][bad_encoding][nrows]: 20
  - :wandb:runs[0][summary][nyt_dep][nrows]: 112
  - :wandb:runs[0][exitcode]: 0
  - :op:contains:
    - :wandb:runs[0][telemetry][3]  # feature
    - 12  # prodigy
"""

import os
import sys
from unittest.mock import Mock
from zipfile import ZipFile

import wandb
from prodigy_connect import Connect
from wandb.integration.prodigy import upload_dataset

sys.modules["prodigy"] = Mock()
sys.modules["prodigy.components"] = Mock()
sys.modules["prodigy.components.db"] = Connect()

# Extract test dataset files downloaded by "yea"
with ZipFile("prodigy_test_resources.zip", "r") as zip_obj:
    zip_obj.extractall()

# Test upload each dataset
run = wandb.init(project="prodigy")
all_files = os.listdir("prodigy_test_resources")
for dataset in all_files:
    dataset_name = dataset.split(".")[0]  # remove .json
    upload_dataset(dataset_name)
wandb.finish()
