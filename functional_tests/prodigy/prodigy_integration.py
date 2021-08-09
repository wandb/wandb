#!/usr/bin/env python
"""Test prodigy integration

---
id: 0.0.1
assert:
  - :wandb:runs_len: 1
  - :wandb:runs[0][summary][ner_dataset][nrows]: 4
  - :wandb:runs[0][exitcode]: 0
"""

from io import BytesIO
import sys
from unittest.mock import Mock
from urllib.request import urlopen
from zipfile import ZipFile

from prodigy_connect import Connect
from wandb.integration.prodigy import upload_dataset

sys.modules['prodigy'] = Mock()
sys.modules['prodigy.components'] = Mock()
sys.modules['prodigy.components.db'] = Connect

# download my files
# run tests

url = "INSERT DATASET URL"
extract_dir = "prodigy_sample_datasets"

http_response = urlopen(url)
zipfile = ZipFile(BytesIO(http_response.read()))
zipfile.extractall(path=extract_dir)
