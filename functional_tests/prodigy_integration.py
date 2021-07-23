import sys
import wandb
from unittest.mock import Mock
from prodigy_connect import connect

sys.modules['prodigy'] = Mock()
sys.modules['prodigy.components'] = Mock()
sys.modules['prodigy.components.db'] = connect

from wandb.integration.prodigy import upload_dataset

## run tests