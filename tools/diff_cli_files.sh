#!/bin/bash
BASE=~/release
diff -u wandb/data/data_types.py ${BASE}/client/wandb/data_types.py
diff -u wandb/internal/stats.py ${BASE}/client/wandb/stats.py
diff -u wandb/internal/internal_api.py ${BASE}/client/wandb/apis/internal.py
diff -u wandb/internal/file_pusher.py ${BASE}/client/wandb/file_pusher.py
diff -u wandb/internal/file_stream.py ${BASE}/client/wandb/apis/file_stream.py
diff -u wandb/wandb_torch.py ${BASE}/client/wandb/wandb_torch.py
