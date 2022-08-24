#!/bin/bash
BASE=~/release
diff -u ${BASE}/wandb/wandb/data_types.py wandb/data_types.py
diff -u ${BASE}/wandb/wandb/stats.py wandb/internal/stats.py
diff -u ${BASE}/wandb/wandb/apis/internal.py wandb/internal/internal_api.py
diff -u ${BASE}/wandb/wandb/file_pusher.py wandb/internal/file_pusher.py
diff -u ${BASE}/wandb/wandb/apis/file_stream.py wandb/internal/file_stream.py
diff -u ${BASE}/wandb/wandb/wandb_torch.py wandb/wandb_torch.py
diff -u ${BASE}/wandb/wandb/keras/__init__.py wandb/framework/keras/keras.py
