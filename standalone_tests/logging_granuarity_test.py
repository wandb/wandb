#!/usr/bin/env python

import os
import time
import random

import wandb

wandb.init()

with open(f'{wandb.run.dir}/0.txt', 'w') as f:
	print('asdf', file=f)

for i in range(3):
	# test support for file renaming. should be a unit test
	os.rename(f'{wandb.run.dir}/{i}.txt', f'{wandb.run.dir}/{i+1}.txt')
	for j in range(10):
		loss = random.random()
		wandb.run.history.add({'mb-loss': loss, 'loss': loss, 'mb': j, 'ep': i})
		time.sleep(1)
	loss = random.random()
	wandb.run.history.add({'ep-loss': loss, 'loss': loss, 'ep': i})
	time.sleep(1)
