#!/usr/bin/env python
"""Test prodigy integration

---
id: 0.0.1
assert:
  - :wandb:runs_len: 1
  - :wandb:runs[0][summary][tumblr_images][nrows]: 108
  - :wandb:runs[0][summary][image_segmentation][nrows]: 34
  - :wandb:runs[0][summary][audio][nrows]: 3
  - :wandb:runs[0][summary][nyt_tokens][nrows]: 200
  - :wandb:runs[0][summary][quora_questions][nrows]: 100
  - :wandb:runs[0][summary][already_labelled][nrows]: 373
  - :wandb:runs[0][summary][products_html][nrows]: 200
  - :wandb:runs[0][summary][unsplash_base64][nrows]: 207
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
"""

import os
import sys
from unittest.mock import Mock
from zipfile import ZipFile

from google.cloud import storage
from prodigy_connect import Connect
import wandb
from wandb.integration.prodigy import upload_dataset

sys.modules['prodigy'] = Mock()
sys.modules['prodigy.components'] = Mock()
sys.modules['prodigy.components.db'] = Connect()

# Download and extract test dataset files
data_url = "gs://prodigy_test_resources/prodigy_test_resources.zip"
client = storage.Client()  # will automatically look for credentials in environment
with open('prodigy_test_resources.zip', 'wb') as file_obj:
    client.download_blob_to_file(data_url, file_obj)
with ZipFile('prodigy_test_resources.zip', 'r') as zip_obj:
    zip_obj.extractall()

# Test upload each dataset
run = wandb.init(project='prodigy')
all_files = os.listdir("prodigy_test_resources")
for dataset in all_files:
    dataset_name = dataset.split(".")[0]  # remove .json
    upload_dataset(dataset_name)
wandb.finish()
