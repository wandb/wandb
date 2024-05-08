#!/usr/bin/env python
import wandb

wb = wandb.new_session()
run = wb.new_run()
run.log({"a": 1, "b": 2})
run.finish()
