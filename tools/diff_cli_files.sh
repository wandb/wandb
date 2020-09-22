#!/bin/bash
BASE=~/release
diff -u ${BASE}/client/wandb/data_types.py wandb/data_types.py
diff -u ${BASE}/client/wandb/stats.py wandb/internal/stats.py 
diff -u ${BASE}/client/wandb/apis/internal.py wandb/internal/internal_api.py
diff -u ${BASE}/client/wandb/file_pusher.py wandb/internal/file_pusher.py
diff -u ${BASE}/client/wandb/apis/file_stream.py wandb/internal/file_stream.py
diff -u ${BASE}/client/wandb/wandb_torch.py wandb/wandb_torch.py
diff -u ${BASE}/client/wandb/keras/__init__.py wandb/framework/keras/keras.py
