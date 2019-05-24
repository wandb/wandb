#!/usr/bin/env python

import os

import wandb

wandb.init()

block = ' ' * 2**20

with open(os.path.join(wandb.run.dir, 'big.file'), 'w') as f:
	for i in range(1000):
		print(block, file=f)
