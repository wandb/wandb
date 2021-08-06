#!/usr/bin/env python
"""Test prodigy integration

---
id: 0.0.1
prep:
  commands:
    - prodigy_download_datasets.py
assert:
  - :wandb:runs_len: 1
  - :wandb:runs[0][summary][ner_dataset][nrows]: 4
  - :wandb:runs[0][exitcode]: 0
"""

import sys
from unittest.mock import Mock

from prodigy_connect import Connect
from wandb.integration.prodigy import upload_dataset

sys.modules['prodigy'] = Mock()
sys.modules['prodigy.components'] = Mock()
sys.modules['prodigy.components.db'] = Connect

# download my files
# run tests
