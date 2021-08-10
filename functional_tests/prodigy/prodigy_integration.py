#!/usr/bin/env python
"""Test prodigy integration

---
id: 0.0.1
assert:
  - :wandb:runs_len: 1
  - :wandb:runs[0][summary][ner_dataset][nrows]: 4
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
